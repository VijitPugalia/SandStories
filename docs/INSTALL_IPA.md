# Install IPA on iPhone (LiveContainer / SideStore)

## Fast path: latest private GitHub build

Successful pushes to `main` publish a direct private IPA asset:

<https://github.com/VijitPugalia/SandStories/releases/download/latest-ipa/SandStories.ipa>

On the iPhone:

1. Log into GitHub in Safari with access to this private repo.
2. Bookmark the link above.
3. After the **Build IPA** action succeeds, open the bookmark.
4. Download `SandStories.ipa`.
5. Import or open the IPA in **LiveContainer** or **SideStore**.

This skips the old Actions artifact ZIP download, unzip step, and Windows transfer. iOS still requires an explicit import/install confirmation.

## Local build fix: app crashes on launch

## Cause

The **xtool-generated** `SandStories.app/Info.plist` does not include iOS **privacy usage** keys. This app uses **ARKit / camera / LiDAR** and **CoreLocation**. Without:

- `NSCameraUsageDescription`
- `NSWorldSensingUsageDescription`
- `NSLocationWhenInUseUsageDescription`

iOS will **terminate the app** when the session accesses the camera (often immediately at launch).

## Fix: merge plist, then package IPA

Use the provided script (recommended):

```bash
cd ~/SandStories
./scripts/build_release_ipa.sh
```

It will:

1. `xtool dev build -c release` (produces `xtool/SandStories.app`)
2. Merge `AppSupport/SandStories-App-Info.plist` into the app’s `Info.plist`
3. Create `xtool/SandStories.ipa` (Payload zip)

Then copy the IPA to Windows and reinstall in LiveContainer or SideStore.

## If you only used `xtool dev build --ipa`

That IPA was built **before** the privacy keys were merged. Rebuild using **`build_release_ipa.sh`** above (or run `merge_privacy_into_app.sh` **before** any manual packaging step).
