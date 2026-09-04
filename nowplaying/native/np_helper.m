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
// established; this is an independent ~60-line implementation of just the
// read path, so nothing third-party needs vendoring.
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

/// Read the current now-playing item and print it as one JSON line.
/// Exported for the perl loader (see np_load.pl).
void np_get(void) {
    @autoreleasepool {
        void *handle = dlopen(kFrameworkPath.UTF8String, RTLD_LAZY);
        if (!handle) {
            emit(@"{\"ok\":false,\"error\":\"framework_unavailable\"}");
            return;
        }
        MRGetNowPlayingInfo_t getInfo = dlsym(handle, "MRMediaRemoteGetNowPlayingInfo");
        if (!getInfo) {
            emit(@"{\"ok\":false,\"error\":\"symbol_missing\"}");
            return;
        }

        __block BOOL done = NO;
        getInfo(dispatch_get_main_queue(), ^(CFDictionaryRef information) {
            NSDictionary *info = (__bridge NSDictionary *)information;
            NSMutableString *out = [NSMutableString stringWithString:@"{\"ok\":true"];

            if (!info || info.count == 0) {
                // Either nothing is playing, or we are not entitled. The caller
                // cannot tell those apart from here, and must not guess: it is
                // reported as "no track", and availability is probed separately.
                [out appendString:@",\"playing\":false"];
            } else {
                // PAUSED IS NOT PLAYING. MediaRemote keeps reporting the last
                // session's track after it is paused, with
                // PlaybackRate == 0 — measured on macOS 26.6.2 with a paused
                // player still owning the Now Playing session. Treating that as
                // "playing" makes a live widget push cover art for something
                // nobody is listening to, and hides a DIFFERENT app that really
                // is playing. The rate is reported so the caller decides.
                double rate = [info[@"kMRMediaRemoteNowPlayingInfoPlaybackRate"] doubleValue];
                [out appendFormat:@",\"playing\":true,\"playback_rate\":%g", rate];
                [out appendFormat:@",\"title\":%@",
                     JSONString(info[@"kMRMediaRemoteNowPlayingInfoTitle"])];
                [out appendFormat:@",\"artist\":%@",
                     JSONString(info[@"kMRMediaRemoteNowPlayingInfoArtist"])];
                [out appendFormat:@",\"album\":%@",
                     JSONString(info[@"kMRMediaRemoteNowPlayingInfoAlbum"])];
                // Reported for diagnostics only. It LIES: on macOS 26.6.2 it
                // says image/jpeg while handing back TIFF bytes, so the caller
                // sniffs the magic instead of trusting this.
                [out appendFormat:@",\"artwork_mime_declared\":%@",
                     JSONString(info[@"kMRMediaRemoteNowPlayingInfoArtworkMIMEType"])];
                NSData *art = info[@"kMRMediaRemoteNowPlayingInfoArtworkData"];
                if (art.length > 0) {
                    [out appendFormat:@",\"artwork_b64\":\"%@\"",
                         [art base64EncodedStringWithOptions:0]];
                }
            }
            [out appendString:@"}"];
            emit(out);
            done = YES;
        });

        // The callback is delivered on the main queue, so we must PUMP the
        // runloop rather than block on a semaphore — waiting would deadlock the
        // very queue the reply needs.
        NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:5.0];
        while (!done && [deadline timeIntervalSinceNow] > 0) {
            [[NSRunLoop mainRunLoop] runMode:NSDefaultRunLoopMode
                                  beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
        }
        if (!done) emit(@"{\"ok\":false,\"error\":\"timeout\"}");
    }
}

/// List every app REGISTERED with Now Playing, as one JSON line.
///
/// # Why this is needed (R67, user-reported)
///
/// `np_get` returns the ONE session macOS considers current, and macOS keeps
/// that session on a player after it is PAUSED. So a paused Kaset masks a
/// playing Feishin, and a caller reading only the session concludes that Feishin
/// is not playing — when in fact Feishin was never a candidate.
///
/// Enumerating the clients separates two very different facts:
///   * "this app is registered and could own the session", versus
///   * "this app is what is playing right now".
///
/// It also answers a question that otherwise needs the user to quit apps: an app
/// ABSENT from this list does not publish to Now Playing at all, and can only be
/// reached by its own mechanism. Measured 2026-08-29: Kaset appears (twice — the
/// app and its WebKit GPU helper), Feishin does not.
///
/// NOTE: `MRMediaRemoteGetNowPlayingApplicationDisplayName` and
/// `...ApplicationPID` SEGFAULT when called this way on macOS 26.6.2. The two
/// accessors used here do not. Do not "simplify" this by switching to them.
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
        if (!getClients) {
            emit(@"{\"ok\":false,\"error\":\"symbol_missing\"}");
            return;
        }

        __block BOOL done = NO;
        getClients(dispatch_get_main_queue(), ^(CFArrayRef arr) {
            NSMutableString *out =
                [NSMutableString stringWithString:@"{\"ok\":true,\"players\":["];
            CFIndex n = arr ? CFArrayGetCount(arr) : 0;
            BOOL first = YES;
            for (CFIndex i = 0; i < n; i++) {
                const void *client = CFArrayGetValueAtIndex(arr, i);
                if (!client) continue;
                CFStringRef bundle = getBundle ? getBundle(client) : NULL;
                CFStringRef name = getName ? getName(client) : NULL;
                if (!first) [out appendString:@","];
                first = NO;
                [out appendFormat:@"{\"bundle_id\":%@,\"name\":%@}",
                     JSONString((__bridge NSString *)bundle),
                     JSONString((__bridge NSString *)name)];
            }
            [out appendString:@"]}"];
            emit(out);
            done = YES;
        });

        NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:5.0];
        while (!done && [deadline timeIntervalSinceNow] > 0) {
            [[NSRunLoop mainRunLoop] runMode:NSDefaultRunLoopMode
                                  beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
        }
        if (!done) emit(@"{\"ok\":false,\"error\":\"timeout\"}");
    }
}
