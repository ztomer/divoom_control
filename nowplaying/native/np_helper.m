// np_helper.m — the entitled host for MediaRemote.
//
// WHY THIS EXISTS, AND WHY IT IS SO ODD
//
// Now-playing metadata lives in the private MediaRemote framework. Since macOS
// 15.4 Apple gates `MRMediaRemoteGetNowPlayingInfo` behind an entitlement: an
// ordinary process can dlopen the framework and resolve the symbol — both
// succeed — and then the callback hands back a NULL dictionary. Probed on
// macOS 26.6.2 (2026-08-29): dlopen OK, dlsym OK, callback NULL_DICT.
//
// `/usr/bin/perl` ships WITH that entitlement. A dylib it loads runs inside
// perl's process and inherits it, so the same call returns real data. That is
// the whole trick, and it is why this is a dylib driven by a perl one-liner
// rather than a normal executable: the entitlement belongs to the host process,
// and we cannot grant it to ourselves.
//
// The approach is the one `mediaremote-adapter` (BSD-3, Jonas van den Berg)
// established; this is an independent implementation of just the read path,
// so nothing third-party needs vendoring.
//
// SIGNATURES (macOS 26.6.2, read from the framework's own code on 2026-09-12
// with `dyld_info -exports` plus an in-process disassembly of each entry
// point, because there is no header and a guessed argument order SEGFAULTS):
//
//   MRMediaRemoteGetNowPlayingInfo(queue, block(CFDictionaryRef))
//   MRMediaRemoteGetLocalOrigin() -> MROrigin
//   MRMediaRemoteGetActivePlayerPathsForOrigin(origin, queue, block(CFArrayRef))
//   MRMediaRemoteGetPlaybackStateForPlayer(path, queue, block(uint32_t))
//   MRMediaRemoteGetNowPlayingInfoForPlayer(path, Boolean includeArtwork, queue, block)
//   MRMediaRemoteGetNowPlayingInfoForClient(client, origin, Boolean includeArtwork, queue, block)
//     = [[MRPlayerPath alloc] initWithOrigin:origin client:client player:nil]
//       then ...InfoForPlayer(path, includeArtwork, queue, block)
//   MRMediaRemoteGetPlaybackStateForClient(client, origin, queue, block(uint32_t))
//   MRMediaRemoteCopyPlaybackStateDescription(state) -> CFStringRef
//     0 Unknown, 1 Playing, 2 Paused, 3 Stopped, 4 Interrupted, 5 Seeking
//
// The "ForClient" read had been declared here as (client, queue, block) and
// written off as a platform limit when it crashed. It takes five arguments.
//
// Output: exactly one line of JSON on stdout, then return. Errors are JSON too
// — a caller must never have to distinguish "no output" from "crashed".

#import <Foundation/Foundation.h>
#include <dlfcn.h>

static NSString *const kFrameworkPath =
    @"/System/Library/PrivateFrameworks/MediaRemote.framework/MediaRemote";

typedef void (*MRGetNowPlayingInfo_t)(dispatch_queue_t, void (^)(CFDictionaryRef));
typedef void (*MRGetNowPlayingClients_t)(dispatch_queue_t, void (^)(CFArrayRef));
typedef CFStringRef (*MRClientAccessor_t)(const void *);
typedef const void *(*MRGetLocalOrigin_t)(void);
typedef void (*MRGetActivePaths_t)(const void *origin, dispatch_queue_t, void (^)(CFArrayRef));
typedef void (*MRStateForPlayer_t)(const void *path, dispatch_queue_t, void (^)(uint32_t));
typedef void (*MRInfoForPlayer_t)(const void *path, Boolean art, dispatch_queue_t, void (^)(CFDictionaryRef));
typedef void (*MRStateForClient_t)(const void *client, const void *origin, dispatch_queue_t, void (^)(uint32_t));
typedef const void *(*MRPathGetClient_t)(const void *path);
typedef CFStringRef (*MRStateDescription_t)(uint32_t);

enum { kStatePlaying = 1 };

/// JSON-encode one string, quotes included. Round-tripping through
/// NSJSONSerialization handles quotes, backslashes, newlines and non-BMP
/// characters — track titles contain all of them.
static NSString *JSONString(NSString *s) {
    if (!s) return @"null";
    NSData *d = [NSJSONSerialization dataWithJSONObject:@[s] options:0 error:nil];
    if (!d) return @"null";
    NSString *arr = [[NSString alloc] initWithData:d encoding:NSUTF8StringEncoding];
    return [arr substringWithRange:NSMakeRange(1, arr.length - 2)];
}

static void emit(NSString *json) {
    printf("%s\n", json.UTF8String);
    fflush(stdout);
}

/// The callbacks are delivered on the main queue, so we must PUMP the runloop
/// rather than block on a semaphore — waiting would deadlock the very queue
/// the reply needs.
static BOOL pump(BOOL *done, NSTimeInterval seconds) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:seconds];
    while (!*done && [deadline timeIntervalSinceNow] > 0) {
        [[NSRunLoop mainRunLoop] runMode:NSDefaultRunLoopMode
                              beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];
    }
    return *done;
}

/// The track fields of one info dictionary as a JSON fragment (leading comma).
static void appendTrack(NSMutableString *out, NSDictionary *info) {
    // PAUSED IS NOT PLAYING. MediaRemote keeps reporting the last session's
    // track after it is paused, with PlaybackRate == 0 — measured on macOS
    // 26.6.2. The rate is reported so the caller decides.
    double rate = [info[@"kMRMediaRemoteNowPlayingInfoPlaybackRate"] doubleValue];
    [out appendFormat:@",\"playing\":true,\"playback_rate\":%g", rate];
    [out appendFormat:@",\"title\":%@", JSONString(info[@"kMRMediaRemoteNowPlayingInfoTitle"])];
    [out appendFormat:@",\"artist\":%@", JSONString(info[@"kMRMediaRemoteNowPlayingInfoArtist"])];
    [out appendFormat:@",\"album\":%@", JSONString(info[@"kMRMediaRemoteNowPlayingInfoAlbum"])];
    // Reported for diagnostics only. It LIES: on macOS 26.6.2 it says
    // image/jpeg while handing back TIFF bytes, so the caller sniffs the magic
    // instead of trusting this.
    [out appendFormat:@",\"artwork_mime_declared\":%@",
         JSONString(info[@"kMRMediaRemoteNowPlayingInfoArtworkMIMEType"])];
    NSData *art = info[@"kMRMediaRemoteNowPlayingInfoArtworkData"];
    if (art.length > 0) {
        [out appendFormat:@",\"artwork_b64\":\"%@\"", [art base64EncodedStringWithOptions:0]];
    }
}

/// The system's ONE elected session, the pre-2026-09-12 read. Still the
/// answer when no player is actually playing (a paused holder is reported
/// with rate 0, an empty holder as nothing).
static void emitElectedSession(MRGetNowPlayingInfo_t getInfo, NSString *playersJSON) {
    __block BOOL done = NO;
    getInfo(dispatch_get_main_queue(), ^(CFDictionaryRef information) {
        NSDictionary *info = (__bridge NSDictionary *)information;
        NSMutableString *out = [NSMutableString stringWithString:@"{\"ok\":true,\"source\":\"elected\""];
        if (!info || info.count == 0) {
            [out appendString:@",\"playing\":false"];
        } else {
            appendTrack(out, info);
        }
        [out appendFormat:@",\"players\":%@}", playersJSON];
        emit(out);
        done = YES;
    });
    if (!pump(&done, 5.0)) emit(@"{\"ok\":false,\"error\":\"timeout\"}");
}

/// Read the current track and print it as one JSON line.
///
/// Every active player path is asked for its playback state; the first one
/// PLAYING is the track, whoever holds the elected session. That is the
/// masking fix (2026-09-12): macOS hands the Now Playing session to the last
/// app that touched it and keeps it there when that app pauses or sits empty,
/// so a stopped Music masked an audibly playing Kaset for a reader of the one
/// elected session. With no player playing, the elected session is reported
/// as before. Exported for the perl loader (see np_load.pl).
void np_get(void) {
    @autoreleasepool {
        void *handle = dlopen(kFrameworkPath.UTF8String, RTLD_LAZY);
        if (!handle) {
            emit(@"{\"ok\":false,\"error\":\"framework_unavailable\"}");
            return;
        }
        MRGetNowPlayingInfo_t getInfo = dlsym(handle, "MRMediaRemoteGetNowPlayingInfo");
        MRGetLocalOrigin_t localOrigin = dlsym(handle, "MRMediaRemoteGetLocalOrigin");
        MRGetActivePaths_t activePaths = dlsym(handle, "MRMediaRemoteGetActivePlayerPathsForOrigin");
        MRStateForPlayer_t stateFor = dlsym(handle, "MRMediaRemoteGetPlaybackStateForPlayer");
        MRInfoForPlayer_t infoFor = dlsym(handle, "MRMediaRemoteGetNowPlayingInfoForPlayer");
        MRPathGetClient_t pathClient = dlsym(handle, "MRNowPlayingPlayerPathGetClient");
        MRClientAccessor_t getBundle = dlsym(handle, "MRNowPlayingClientGetBundleIdentifier");
        MRClientAccessor_t getParent = dlsym(handle, "MRNowPlayingClientGetParentAppBundleIdentifier");
        MRClientAccessor_t getName = dlsym(handle, "MRNowPlayingClientGetDisplayName");
        MRStateDescription_t stateName = dlsym(handle, "MRMediaRemoteCopyPlaybackStateDescription");
        if (!getInfo) {
            emit(@"{\"ok\":false,\"error\":\"symbol_missing\"}");
            return;
        }
        // The per-player set is a 2026 reading of the framework; without it
        // (an older macOS) the elected session is all there is.
        BOOL perPlayer = localOrigin && activePaths && stateFor && infoFor;
        if (!perPlayer) {
            emitElectedSession(getInfo, @"[]");
            return;
        }

        const void *origin = localOrigin();
        __block BOOL done = NO;
        __block NSArray *paths = nil;
        activePaths(origin, dispatch_get_main_queue(), ^(CFArrayRef arr) {
            paths = arr ? [(__bridge NSArray *)arr copy] : @[];
            done = YES;
        });
        if (!pump(&done, 5.0)) {
            emit(@"{\"ok\":false,\"error\":\"timeout\"}");
            return;
        }

        NSMutableString *players = [NSMutableString stringWithString:@"["];
        id chosen = nil;
        for (id path in paths) {
            const void *client = pathClient ? pathClient((__bridge const void *)path) : NULL;
            NSString *bundle = client && getBundle ? (__bridge NSString *)getBundle(client) : nil;
            NSString *parent = client && getParent ? (__bridge NSString *)getParent(client) : nil;
            NSString *name = client && getName ? (__bridge NSString *)getName(client) : nil;
            __block BOOL got = NO;
            __block uint32_t state = 0;
            stateFor((__bridge const void *)path, dispatch_get_main_queue(), ^(uint32_t s) {
                state = s;
                got = YES;
            });
            pump(&got, 2.0);
            NSString *stateStr = stateName ? (__bridge_transfer NSString *)stateName(state) : nil;
            if (players.length > 1) [players appendString:@","];
            [players appendFormat:@"{\"bundle_id\":%@,\"parent_bundle_id\":%@,\"name\":%@,\"state\":%@}",
                 JSONString(bundle), JSONString(parent), JSONString(name),
                 JSONString(stateStr ?: [NSString stringWithFormat:@"%u", state])];
            if (!chosen && got && state == kStatePlaying) chosen = path;
        }
        [players appendString:@"]"];

        if (!chosen) {
            emitElectedSession(getInfo, players);
            return;
        }
        const void *client = pathClient ? pathClient((__bridge const void *)chosen) : NULL;
        NSString *bundle = client && getBundle ? (__bridge NSString *)getBundle(client) : nil;
        NSString *parent = client && getParent ? (__bridge NSString *)getParent(client) : nil;
        __block BOOL gotInfo = NO;
        infoFor((__bridge const void *)chosen, true, dispatch_get_main_queue(), ^(CFDictionaryRef information) {
            NSDictionary *info = (__bridge NSDictionary *)information;
            NSMutableString *out = [NSMutableString stringWithString:@"{\"ok\":true,\"source\":\"player\""];
            [out appendFormat:@",\"bundle_id\":%@,\"parent_bundle_id\":%@,\"state\":\"Playing\"",
                 JSONString(bundle), JSONString(parent)];
            if (!info || info.count == 0) {
                [out appendString:@",\"playing\":false"];
            } else {
                appendTrack(out, info);
            }
            [out appendFormat:@",\"players\":%@}", players];
            emit(out);
            gotInfo = YES;
        });
        if (!pump(&gotInfo, 5.0)) emit(@"{\"ok\":false,\"error\":\"timeout\"}");
    }
}

/// List every app REGISTERED with Now Playing, as one JSON line, each with
/// its playback state.
///
/// Registration is not playback: an app in this list could own the session;
/// an app ABSENT from it does not publish to Now Playing at all and can only
/// be reached by its own mechanism. Measured 2026-08-29: Kaset appears
/// (twice — the app and its WebKit GPU helper), Feishin does not.
///
/// NOTE: `MRMediaRemoteGetNowPlayingApplicationDisplayName` and
/// `...ApplicationPID` SEGFAULT when called with a client. The accessors
/// used here do not.
void np_players(void) {
    @autoreleasepool {
        void *handle = dlopen(kFrameworkPath.UTF8String, RTLD_LAZY);
        if (!handle) {
            emit(@"{\"ok\":false,\"error\":\"framework_unavailable\"}");
            return;
        }
        MRGetNowPlayingClients_t getClients =
            dlsym(handle, "MRMediaRemoteGetNowPlayingClients");
        MRClientAccessor_t getBundle = dlsym(handle, "MRNowPlayingClientGetBundleIdentifier");
        MRClientAccessor_t getName = dlsym(handle, "MRNowPlayingClientGetDisplayName");
        MRGetLocalOrigin_t localOrigin = dlsym(handle, "MRMediaRemoteGetLocalOrigin");
        MRStateForClient_t stateFor = dlsym(handle, "MRMediaRemoteGetPlaybackStateForClient");
        MRStateDescription_t stateName = dlsym(handle, "MRMediaRemoteCopyPlaybackStateDescription");
        if (!getClients) {
            emit(@"{\"ok\":false,\"error\":\"symbol_missing\"}");
            return;
        }
        const void *origin = localOrigin ? localOrigin() : NULL;

        __block BOOL done = NO;
        __block NSArray *clients = nil;
        getClients(dispatch_get_main_queue(), ^(CFArrayRef arr) {
            clients = arr ? [(__bridge NSArray *)arr copy] : @[];
            done = YES;
        });
        if (!pump(&done, 5.0)) {
            emit(@"{\"ok\":false,\"error\":\"timeout\"}");
            return;
        }
        NSMutableString *out = [NSMutableString stringWithString:@"{\"ok\":true,\"players\":["];
        BOOL first = YES;
        for (id c in clients) {
            const void *client = (__bridge const void *)c;
            CFStringRef bundle = getBundle ? getBundle(client) : NULL;
            CFStringRef name = getName ? getName(client) : NULL;
            NSString *stateStr = nil;
            if (origin && stateFor && stateName) {
                __block BOOL got = NO;
                __block uint32_t state = 0;
                stateFor(client, origin, dispatch_get_main_queue(), ^(uint32_t s) {
                    state = s;
                    got = YES;
                });
                if (pump(&got, 2.0)) stateStr = (__bridge_transfer NSString *)stateName(state);
            }
            if (!first) [out appendString:@","];
            first = NO;
            [out appendFormat:@"{\"bundle_id\":%@,\"name\":%@,\"state\":%@}",
                 JSONString((__bridge NSString *)bundle),
                 JSONString((__bridge NSString *)name), JSONString(stateStr)];
        }
        [out appendString:@"]}"];
        emit(out);
    }
}
