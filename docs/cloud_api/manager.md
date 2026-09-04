# Manager/Discount/Medal/Shop API

Source: decompiled Divoom Android app (JADX), `references/apk/decompiled_src/sources/com/divoom/Divoom/`
(gitignored, not checked in). Master list: `http/HttpCommand.java`. As expected for this batch, this
domain is almost entirely Divoom's own backend-moderation/admin panel (the `Manager/*` and report/
signature/gallery-review commands), plus e-commerce discount codes (`Discount/*`, `Shop/*`) and
gamification medals (`Medal/*`). None of the 28 commands below touch device control.

Two web searches were run to check for public documentation:
- `divoom "Manager/PassGallery" OR "Manager/GetUserInfo" API"` — surfaced one third-party
  reverse-engineered catalog, the REvoom Team's endpoint list (`divoom.2a03.party/api/app.html`).
- `divoom-gz.com API documentation Discount Medal Shop moderation` — no results specific to this
  domain; only the official local-device API docs (`doc.divoom-gz.com`, unrelated to these cloud
  admin/e-commerce endpoints) and generic third-party device-control API wrappers.

The REvoom page lists `Manager/AddGood`, `Manager/AddRemoveRecommend`, `Manager/ChangeClassify`,
`Manager/PassGallery`, `Manager/SetFillGameScore`, `Discount/Delete`, `Discount/GetMyList`,
`Medal/GetList`, `Medal/GetNewValidList` in its "undocumented endpoints" name-only list (no field
detail), and separately notes `Manager/PassGallery` "always returns 1 (Failed)" — consistent with our
finding below that it has no live caller in the current app build and appears superseded by
`Manager/PassGalleryV2`. No other command in this batch appears on any public page found. This
confirms the expectation: essentially nothing public exists for this domain beyond decompiled source.

## Table

| Command | Purpose | Request fields | Response fields | Relevance | Confidence |
|---|---|---|---|---|---|
| `Manager/AddGood` | Admin toggles a "good"/featured flag on a gallery item (curation marker). | `ManagerAddGoodRequest`: `AddGood`(int), `GalleryId`(int) | `BaseResponseJson` (generic ReturnCode) | internal/moderation | decompiled (request class only — no live call site found in current build) |
| `Manager/AddPixelAmb` | Admin grants/revokes a "PixelAmb" type flag on a target user (ambassador/badge-style moderation flag). | `ManagerAddPixelAmbRequest`: `AddFlag`(int), `PixelAmbTypeId`(int), `TargetUserId`(int) | `BaseResponseJson` | internal/moderation | decompiled (caller: `CloudHttpModel.java`) |
| `Manager/AddRemoveRecommend` | Admin adds/removes a gallery item from the recommended/featured list. | `AddRemoveRecommendRequest`: `Add`(int, 0/1), `GalleryId`(int), `Type`(int) | `BaseResponseJson` | internal/moderation | decompiled (caller: `CloudModelV2.a()`) |
| `Manager/ChangeClassify` | Admin reassigns a gallery item to a different category/classify id. | `ChangeClassifyRequest`: `GalleryId`(int), `Classify`(int) | `BaseResponseJson` | internal/moderation | decompiled (caller: `CloudModelV2.b()`) |
| `Manager/GetReportCommentList` | Admin fetches a paginated queue of reported comments pending review. | generic `BaseLoadMoreRequest`: `StartNum`, `EndNum`, `Language`, `CountryISOCode` | `ManagerGetReportCommentListResponse`: `ReportList` → `ReportListItem`{`BeReportHeadId`, `BeReportNickName`, `BeReportUesrId`, `ClockId`, `Comment`, `CommentClassify`, `CommentId`, `ForumId`, `GalleryId`, `ReportId`, `ReportInfo`, `ReportUserId`} | internal/moderation | decompiled (caller: `CloudVerifyCommentFragment.java`) |
| `Manager/GetReportGallery` | Admin fetches a paginated queue of reported/flagged gallery uploads. | `ManagerGetReportGalleryRequest`: `StartNum`(int), `EndNum`(int) | `CloudListResponseV2` (generic gallery file-list response, reused from the normal gallery-browse endpoints) | internal/moderation | decompiled (caller: `CloudReportGalleryModel.b()`) |
| `Manager/GetReportMessageGroupList` | Admin fetches a paginated queue of reported chat/message-group content. | generic `BaseLoadMoreRequest` (same as above) | `ManagerGetReportMessageGroupListResponse`: `ReportList` → `MessageGroupReportListItem`{`BeReportHeadId`, `BeReportNickName`, `BeReportUesrId`, `BusChannel`, `MessageImageUrl`, `MessagePixelFileId`, `MessageText`, `MessageUID`, `MessageVideoUrl`, `ReportId`, `ReportText`, `ReportType`, `ReportUserId`, `SentTime`, `TargetId`} | internal/moderation | decompiled (caller: `CloudVerifySuperGroupFragment.java`) |
| `Manager/GetReportUserList` | Admin fetches a paginated queue of reported users pending review. | generic `BaseLoadMoreRequest` (same as above) | `ManagerGetReportUserListResponse`: `ReportList` → `ReportListItem` (same shape as GetReportCommentList) | internal/moderation | decompiled (caller: `CloudVerifyUserFragment.java`; Java constant is oddly named `ManagerPassGetReportUserList` but its string value is `"Manager/GetReportUserList"`) |
| `Manager/GetSignatureList` | Admin fetches a paginated queue of user profile "signatures" (bios) pending moderation. | `ManagerGetSignatureListRequest`: `StartNum`(int), `EndNum`(int) | `ManagerGetSignatureListResponse`: `SignatureList` → `ManagerGetSignatureItem`{`HeadId`, `NickName`, `Signature`, `SignatureId`, `UserId`} | internal/moderation | decompiled (caller: `CloudVerifySignatureFragment.java`) |
| `Manager/GetUserInfo` | Admin fetches a target user's info blob for moderation review context. | `BaseRequestJson` (empty — no target-user field is set at the call site, i.e. relies on session context, or the call is incomplete) | `ManagerGetUserInfoResponse`: `UserInfo`(String — raw JSON blob, not further parsed) | internal/moderation | decompiled (caller: `CloudLongOnClickModel.java`) |
| `Manager/LimitComment` | Admin bans/restricts a user's ability to post comments. | `ManagerLimitCommentRequest`: `TargetUserId`(int) | `BaseResponseJson` | internal/moderation | decompiled (caller: `VerifyModel.e()`/`f()`) |
| `Manager/LimitSuperGroup` | Admin restricts a user's ability to participate in "super group" chat messaging. | `ManagerLimitSuperGroupRequest`: `TargetUserId`(int), `Limit`(int) | `BaseResponseJson` | internal/moderation | decompiled (caller: `VerifyModel.n()`) |
| `Manager/LimitUpload` | Admin bans/restricts a user's ability to upload gallery content. | `ManagerLimitUploadRequest`: `TargetUserId`(int) | `BaseResponseJson` | internal/moderation | decompiled (caller: `VerifyModel.g()`) |
| `Manager/PassGallery` | Legacy (v1) admin approve/reject of a single reported gallery item. | `ManagerPassGalleryRequest`: `Classify`(int), `GalleryId`(int), `Pass`(int) | `BaseResponseJson` | internal/moderation | decompiled (request/response classes exist; **no live call site** in current app build — publicly noted by a third-party reverse-engineering site as always failing server-side; superseded by `PassGalleryV2`) |
| `Manager/PassGalleryV2` | Current admin approve/reject of a batch of reported gallery items. | `ManagerPassGalleryV2Request`: `Classify`(int), `GalleryList`(List\<Integer\>), `Pass`(int) | `BaseResponseJson` | internal/moderation | decompiled (caller: `VerifyModel.h()`/`i()`) |
| `Manager/PassReport` | Admin approves/rejects a reported-gallery report entry (used by the report-gallery review screen, distinct from `PassGallery`/`PassGalleryV2` which act on the gallery item itself). | `ManagerPassReportRequest`: `GalleryId`(int), `Pass`(int) | `BaseResponseJson` | internal/moderation | decompiled (caller: `CloudReportGalleryModel.c()`/`d()`) |
| `Manager/PassReportComment` | Admin resolves/dismisses a reported comment. | `ManagerPassReportCommentRequest`: `CommentClassify`(int), `ReportId`(int) | `BaseResponseJson` | internal/moderation | decompiled (caller: `VerifyModel.a()`/`e()`/`j()`) |
| `Manager/PassReportMessageGroup` | Admin resolves/dismisses a reported chat-group message. | `ManagerPassReportMessageGroupRequest`: `ReportId`(int) | `BaseResponseJson` | internal/moderation | decompiled (caller: `VerifyModel.k()`/`n()`) |
| `Manager/PassReportUser` | Admin resolves/dismisses a reported-user report. | `ManagerPassReportUserRequest`: `ReportId`(int) | `BaseResponseJson` | internal/moderation | decompiled (caller: `VerifyModel.f()`/`g()`/`l()`) |
| `Manager/PassSignature` | Admin approves/rejects one or more reported profile signatures (batch). | `ManagerPassSignatureRequest`: `Pass`(int), `SignatureIdArray`(List\<Integer\>) | `BaseResponseJson` | internal/moderation | decompiled (caller: `VerifyModel.m()`) |
| `Manager/SetFillGameScore` | Admin manually overrides the score on a "fill game" gallery entry (leaderboard correction tool). | `FillGameSetScoreRequest`: `GalleryId`(int), `Score`(int) | `BaseResponseJson` | internal/moderation | decompiled (caller: `CloudModelV2.u()`) |
| `Manager/ShowGallery` | Admin un-hides/restores a previously hidden gallery item (moderation counterpart to the user-facing `HideGalleryV2`, reuses its request shape). | `DeleteGalleryV2Request`: `GalleryId`(int) | `BaseResponseJson` | internal/moderation | decompiled (caller: `CloudModelV2.B()`) |
| `Discount/Delete` | Removes/deletes a discount coupon from the current user's held-codes list (e.g. after use or dismissal). | `DiscountDeleteRequest`: `Position`(int) | `BaseResponseJson` | account/social | decompiled (caller: `CloudHttpModel.d()`) |
| `Discount/GetMyList` | Fetches the current user's list of held/claimed discount coupon codes. | `DiscountGetMyListRequest` (empty body) | `DiscountGetMyListResponse`: `DiscountList` → `DiscountListBean`{`DiscountCode`, `ExpireFlag`, `ImageId`, `LinkUrl`, `ValidDate`} | account/social | decompiled (caller: `CloudHttpModel.java`, via `HttpCommand.GetMyList` constant) |
| `Discount/GetNewDiscount` | Fetches new discount/promo announcement banner content, paged by index/region. | `GetAnnouncementRequest` (shared shape): `LastIndex`(int), `RegionId`(int) | `GetAnnouncementResponse`: `ImageId`, `LastIndex`, `LinkUrl`, `filePath` | account/social | decompiled (caller: `CloudVoucherFragment.java`) |
| `Medal/GetList` | Fetches a target user's medal/achievement (gamification badge) list. | `CloudMedalListRequest`: `Langue`(String), `TargetUserId`(int) | `MedalListResponse`: `MedalList` → `MedalListBean`{`ActionType`, `EndTime`, `Explain`, `InValidImageId`, `IsValid`, `MedalId`, `Name`, `StarTime`, `SubTitle`, `ValidImageId`, `ValidTime`}, `MedalValidCnt`(int) | account/social | decompiled (caller: `CloudHttpModel.java`) |
| `Medal/GetNewValidList` | Fetches newly-valid (unlocked/unseen) medals for the current user, likely for a notification badge. | `MedalGetNewValidListRequest`: `Langue`(String) | Not confirmed — no live call site found; presumed to reuse `MedalListResponse` given the shared `Medal/*` family and matching request pattern, but unverified | account/social | name-only (request class decompiled; response type and live usage unconfirmed) |
| `Shop/GetShopAuthLink` | Fetches an authenticated deep-link URL into Divoom's shop/store (SSO handoff for in-app purchases). | `ShopGetShopAuthLinkRequest`: `Url`(String) | `ShopGetShopAuthLinkResponse`: `AuthUrl`(String) | account/social | decompiled (caller: `ShopModel.java`) |

## Unknown / no signal

None. Every command in this batch had at least a decompiled request or response class (`decompiled`)
establishing its field shape; the two weakest entries — `Manager/PassGallery` (no live caller, but
full request/response classes exist and a third-party site independently confirms the endpoint name)
and `Medal/GetNewValidList` (request class exists, but no call site or confirmed response type) — are
tagged `decompiled` and `name-only` respectively rather than `unknown`, since real field-level signal
exists for both.
