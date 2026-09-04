# Top-level API (batch A)

Source: decompiled Divoom Android app (JADX), `references/apk/decompiled_src/sources/com/divoom/Divoom/`
(gitignored). Master list `http/HttpCommand.java`; request shapes `http/request/**`
(`@JSONField`); response shapes `http/response/**`; callers found by grepping
`HttpCommand.<Name>` across `view/fragment/**` and `**/model/*.java`.

All requests extend `BaseRequestJson` (implicit fields on every call, not
repeated per-row below): `Command`, `Token`, `UserId`, `DeviceId`,
`DevicePassword`, `LocalToken`. All responses extend `BaseResponseJson`
(implicit on every row): `Command`, `DeviceId`, `ReturnCode`, `ReturnMessage`,
`androidCacheTime`. Only the command-specific extra fields are listed below.

Public docs check (2 web searches, one page fetch of the community
reverse-engineering doc at `divoom.2a03.party/api/app.html`): none of these 32
commands have field-level public documentation. That site lists all of them
(except `GetNewAppVersion`) in its "undocumented endpoints" bucket with no
field detail — it corroborates only `GetNewAppVersion`'s `IsAndroid` request
field, `Describe`/`Version` response fields, and its own editorial note that
`GetNewAppVersion` looks like a "seemingly outdated endpoint." No public
source contradicts anything decompiled below.

| Command | Purpose | Request fields | Response fields | Relevance | Confidence |
|---|---|---|---|---|---|
| `AddDownloads` | Legacy ("cloudOld") — record that the user downloaded a gallery file, for download-count tracking. | `FileId` (String) | generic (`ReturnCode` only) | account/social | decompiled |
| `AddWatch` | Add a gallery item to the user's watch/subscribe list (`CloudAddWatchRequest`). | `Classify` (int), `GalleryId` (int), `Type` (int) | generic | account/social | decompiled |
| `ApplyBuddy` | Send a buddy (friend) request by email (`DealBuddyRequest`, shared with `ConfirmBuddy`/`RefuseBuddy`). | `Email` (String) | generic | account/social | decompiled |
| `ChangPassword` | Change the logged-in user's password (note: typo "Chang" not "Change" is the real wire command). | `OldPassword` (String), `NewPassword` (String) | generic | account/social | decompiled |
| `CheckIdentifyCode` | Verify an emailed identify/verification code (used in the password-reset flow, also in `retryIPCommand` — a command list that gets retried against a fallback server IP on failure). | `Email` (String), `IdentifyCode` (int) | generic | account/social | decompiled |
| `CommentLikeV2` | Like/unlike a comment on a gallery item. | `CommentId` (int), `IsLike` (int) | generic | account/social | decompiled |
| `ConfirmBuddy` | Accept a pending buddy request (`DealBuddyRequest`, same shape as `ApplyBuddy`). | `Email` (String) | generic | account/social | decompiled |
| `ConfirmGetNewLetterV2` | Acknowledge/mark-read the fetched "new letters" (in-app chat/notification messages) up to a paging cursor. | `LastIndex` (String) | generic | account/social | decompiled |
| `DeleteFile` | Legacy ("cloudOld") — delete a file the user owns from cloud storage (predecessor of `DeleteGalleryV2`). | `FileId` (String) | generic | account/social | decompiled |
| `DeleteGalleryV2` | Delete a gallery post the user owns (current, non-legacy delete path; `CloudModelV2`). | `GalleryId` (int) | generic | account/social | decompiled |
| `DiscoverBanner` | Fetch promotional banner images/links shown on the app's discover/home screen, filtered by region. | `RegionId` (int) | `BannerList[]`: `AdvertName`, `ImageId`, `LinkUrl` | device-control (servable content, ad/banner surface only) | decompiled |
| `EveryDayMission` | Fetch the user's daily-mission / gamification progress (login streak, design count, share count, comment count, AI/fill-game missions, XP level). | (none — empty body) | `CurLevel`, `NextLevelTotalExp`, `DiffExp`, `MissionLogin`, `MissionDesign`, `MissionShare`, `MissionComment`, `MissionAI`, `MissionFillGame`, `MissionFollow` | account/social | decompiled |
| `FindPassword` | Complete a password reset using an emailed identify code (paired with `CheckIdentifyCode`; both in `retryIPCommand`). | `Email` (String), `IdentifyCode` (int), `NewPassword` (String) | generic | account/social | decompiled |
| `FollowExpertV2` | Follow/unfollow another user ("expert" = a gallery content creator/curator). | `IsFollow` (int), `SomeOneUserId` (int) | generic | account/social | decompiled |
| `GalleryLikeV2` | Like/unlike a gallery post. | `Classify` (int), `GalleryId` (int), `IsLike` (int), `Type` (int) | generic | account/social | decompiled |
| `GalleryUpload` | **Dead/legacy constant.** Declared in `HttpCommand.java` but grepped zero live callers anywhere in the decompiled app. The real upload path found (`e3/g.java`, `PixelBean.uploadToSeverRxJava`) posts to `CloudGalleryUploadV3` / `CloudGalleryAsyncUploadV3` (domain-prefixed, out of this batch) using `GalleryUploadRequestV2` → `GalleryUploadV3Response`. Public community doc (`divoom.2a03.party`) separately notes a `Cloud/GalleryUploadV3` endpoint with fields `Classify`, `Content`, `CopyrightFlag`, `DeviceId`, `FileMD5`, `FileName`, `FileSize`, `FileType` — consistent with the V3 path being current and this bare `GalleryUpload` name being superseded. | n/a (unused) | n/a (unused) | account/social | decompiled (superseded, unused) |
| `GalleryUploadV2` | **Dead/legacy constant**, same situation as `GalleryUpload` — declared, zero live callers; superseded by `CloudGalleryUploadV3`/`CloudGalleryAsyncUploadV3`. Public doc separately confirms an actual `http://app.divoom-gz.com/GalleryUploadV2` endpoint existed historically, so this was once live and later replaced. | n/a (unused) | n/a (unused) | account/social | decompiled (superseded, unused) |
| `GetBuddyInfo` | Fetch the current user's buddy/friend-request status summary (used to badge the buddy-request inbox). | (none — empty body, auth-only) | `BuddyFlag`, `Email`, `HeadId`, `NickName`, `Rename`, `UserId`, `UserSign` | account/social | decompiled |
| `GetCategoryFileList` | **Legacy predecessor of `GetCategoryFileListV2`** — still has a live caller (`OldCloudModel.java` → `OldCloudCategoryFragment`, "cloudOld" package), so not fully dead in this APK build, but superseded/secondary path. | `Category` (int), `StartNum`/`EndNum` (int), `FileSize` (int), `FileType` (int) | `CurListNum` (int), `FileList[]` (legacy, thinner shape than V2's `CloudListResponseV2.FileListBean`) | device-control (legacy content list) | decompiled |
| `GetCategoryFileListV2` | **Already implemented and shipping** in this project — the pixel-art / clock-face / "monthly best" cloud gallery browser (`divoom_lib/cloud.py::get_category_file_list`, used by `list_clock_faces`). Documented from actual project source, not re-derived from the APK. | Project's live wire body: `Command`, `Token`, `UserId`, `DeviceId`, `Classify`, `FileSort`, `FileType`, `FileSize`, `Version`, `StartNum`, `EndNum`, `RefreshIndex`, optional `DevicePassword` (matches decompiled `GetCategoryRequestV2`/`GetCloudBaseRequestV2` shape: `Classify`, `EndNum`, `FileSort`, `RefreshIndex`, `StartNum`, `FileType`, `FileSize`, `Version`). | `ReturnCode`, `ReturnMessage`, and either `FileList` or `List` (project code checks both keys) — decompiled `CloudListResponseV2.FileListBean` has ~40 fields incl. `FileId`, `FileName`, `GalleryId`, `UserId`, `Classify`, `FileType`, `Date`, `LikeCnt`, `CommentCnt`, `IsLike`, `PrivateFlag`, `CopyrightFlag`, `AtList`, `content` | device-control (already shipped) | decompiled + device-control + already shipped |
| `GetCommentListV2` | Fetch the comment thread for a gallery post. | `EndNum`/`StartNum` (int), `GalleryId` (int), `Language` (String) | `CommentListNum`, `CurListNum`, `CommentList[]`: `Comment`, `CommentId`, `CountryISOCode`, `Date`, `HeadId`, `IsLike`, `Level`, `LikeCnt`, `NickName`, `PixelAmbId`, `PixelAmbName`, `RegionId`, `UserId` | account/social | decompiled |
| `GetExpertListV4` | Fetch the curated "expert" (featured creator) list with their showcase files. | `ExpertListV2Request`: `EndNum`/`StartNum` (int), `FileType` (int), `Language` (String), `RefreshIndex` (int), `FileSize`=127, `Version`=19 | `ExpertListV2Response`: `CurListNum`, `ExpertListNum`, `ExpertList[]`: `CountryISOCode`, `FansCnt`, `FileList[]` (nested `CloudListResponseV2.FileListBean`), `HeadId`, `IsFollow`, `Level`, `MedalList[]`, `NickName`, `PixelAmbId`/`Name`, `RegionId`, `Score`, `UserId` | account/social | decompiled |
| `GetFansListV2` | Fetch the current user's fans (followers) list. Shares implementation with `GetFollowListV2` — same `CloudHttpModel.f(view, command, start, end, refresh)` method, dispatched by passing the command name as a string param. **Note:** a dedicated `GetFansListV2Request` class exists in source (`EndNum`/`StartNum`) but is dead/unused — the real live request is `ExpertListV2Request` (see `GetExpertListV4` row). | live: `ExpertListV2Request` fields (`StartNum`, `EndNum`, `Language`, etc.) | `GetFansListV2Response`: `CurListNum`, `FollowListNum`, `FollowList[]` (`SearchUserResponse.UserListBean`) | account/social | decompiled |
| `GetFollowListV2` | Fetch who the current user follows. Same dispatch/shape as `GetFansListV2` (see above); the code path sets `IsFollow=1` on each result specifically for this command. | `ExpertListV2Request` fields | `GetFansListV2Response` (same class, reused) | account/social | decompiled |
| `GetGalleryAdvert` | Fetch a single rotating gallery advertisement/banner, paged via `LastIndex`. Distinct from `NoDevice/GetGalleryAdvert` (a separate domain-prefixed sibling command, out of scope). | `CountryISOCode` (String), `Language` (String), `LastIndex` (int), `RegionId` (int) | `AdvertName`, `ImageId`, `LastIndex`, `LinkUrl` | device-control (servable ad content) | decompiled |
| `GetMyLikeListV3` | Fetch gallery posts the current user has liked. Dispatches through the same generic `str`-parameterized fetch as `GetMyUploadListV3`/`GetSomeoneListV3` in `CloudModelV2.java` (line ~212), using `GetCloudBaseRequestV2` → `CloudListResponseV2`. Explicitly bypassed for Kids-mode accounts. | `GetCloudBaseRequestV2`: `Classify`, `EndNum`, `FileSort`, `RefreshIndex`, `StartNum`, `FileType`, `FileSize`=127, `Version`=19 | `CloudListResponseV2`: `FileList[]` (`FileListBean`, ~40 fields — see `GetCategoryFileListV2` row) | account/social | decompiled |
| `GetMyUploadListV3` | Fetch gallery posts the current user has uploaded. Same generic dispatch/shape as `GetMyLikeListV3` above. | `GetCloudBaseRequestV2` | `CloudListResponseV2` | account/social | decompiled |
| `GetNewAppVersion` | Check for a new Android app version (update-nag flow, `AppUpdateChain`). Public community doc independently confirms this shape and separately flags it as a "seemingly outdated endpoint" in their own testing. | `IsAndroid` (int, default 1), `Langue` (String, sic — misspelled "Language") | `Describe` (String), `Version` (int) | device-control (gates app/content compatibility, not device firmware) | decompiled |
| `GetNewLetterListV2` | Fetch new in-app "letters" (chat/system notification messages) since the last cursor. | (none — empty body) | `LastIndex` (String), `LetterList[]`: `HeadId`, `Letter`, `Nickname`, `Time`, `UserId`, `isRight` (boolean, likely "is outgoing/from-me") | account/social | decompiled |
| `GetSomeoneInfoV2` | Fetch another user's public profile (bio, level, follower/fan counts, medals). | `GetSomeoneInfoRequestV2`: `Language` (String), `SomeOneUserId` (int) | `GetSomeoneInfoResponseV2`: `BackgroundId`, `BlackFlag`, `CountryISOCode`, `FansCnt`, `FollowCnt`, `HeadId`, `IsFollow`, `Level`, `LikeCnt`, `MedalList[]`, `MessageFlag`, `NickName`, `PixelAmbId`/`Name`/`TypeId`, `PixelFlag`, `RegionId`, `Relation`, `Score`, `UserNewSign`, `WebUrl` | account/social | decompiled |
| `GetSomeoneListV3` | Fetch another user's uploaded/liked gallery posts (their public profile's content grid). Same generic dispatch as `GetMyUploadListV3`/`GetMyLikeListV3`. | `GetSomeoneListV2Request` (extends `GetCloudBaseRequestV2` + `ShowAllFlag` (int), `SomeOneUserId` (int)) | `CloudListResponseV2` | account/social | decompiled |
| `GetStartLogo` | Fetch the app's splash/start-screen promotional image, region-filtered, with an expiry. | `RegionId` (int) | `ImageId` (String), `InvalidTime` (long), `LinkUrl` (String) | device-control (servable splash content) | decompiled |

## Unknown / no signal

(none — all 32 commands in this batch had a declaration in `http/HttpCommand.java`
and at least a request/response class or a live caller in the decompiled
source; `GalleryUpload`/`GalleryUploadV2` are dead/unused constants but their
classification is still `decompiled`, not `unknown`, since the source
confirms *why* they're unused.)
