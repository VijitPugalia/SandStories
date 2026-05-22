# Fix: app crashes on launch (SideStore / device)

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

Then copy the IPA to Windows and reinstall in SideStore.

## If you only used `xtool dev build --ipa`

That IPA was built **before** the privacy keys were merged. Rebuild using **`build_release_ipa.sh`** above (or run `merge_privacy_into_app.sh` **before** any manual packaging step).
