# Continuous integration (GitHub Actions)

Build SandStories on **Ubuntu** without a Mac. Each successful run on `main` produces a downloadable **`SandStories.ipa`** artifact.

Workflow: [`.github/workflows/build-ipa.yml`](../.github/workflows/build-ipa.yml)

## What runs on every push

1. Install **Swift** and **xtool** (pinned in [`.github/xtool-version.env`](../.github/xtool-version.env))
2. Restore or install the **Darwin Swift SDK** (iOS cross-compile toolchain)
3. Run [`scripts/build_release_ipa.sh`](../scripts/build_release_ipa.sh)
4. Upload `xtool/SandStories.ipa` as a workflow artifact

**Pull requests** also build and upload a short-lived IPA artifact (7 days).  
**Pushes to `main`** and **manual runs** keep artifacts for 30 days.

## Download the IPA

1. Open your repo on GitHub → **Actions**
2. Click the latest **Build IPA** run
3. Under **Artifacts**, download **SandStories-ipa**
4. Install on your iPhone with **SideStore** (same as a local build)

No Mac required for this step.

## One-time bootstrap: Darwin Swift SDK

GitHub-hosted runners do not include Apple’s iOS SDK. You must provide it **once** using one of these options.

### Option A — SDK tarball secret (recommended)

On your **WSL/Linux** machine (after you have run `xtool setup` with `Xcode_16.3.xip`):

```bash
cd ~/SandStories
bash scripts/ci-pack-darwin-sdk.sh ~/darwin-sdk.tar.gz
```

Upload `darwin-sdk.tar.gz` to a **private** URL (personal cloud storage, S3, a private GitHub Release asset, etc.).

In the repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value |
|--------|--------|
| `DARWIN_SDK_TARBALL_URL` | HTTPS URL to `darwin-sdk.tar.gz` |

Re-run **Build IPA**. The SDK is cached under `~/.swiftpm/swift-sdks` for faster later runs.

### Option B — Self-hosted runner + Xcode.xip

1. Add a [self-hosted Linux runner](https://docs.github.com/en/actions/hosting-your-own-runners) with `Xcode_16.3.xip` on disk
2. Set secret `XCODE_XIP_PATH` to the full path (e.g. `/opt/Xcode_16.3.xip`)
3. CI runs `xtool sdk install` on first use

### Option C — Local build only

Skip CI and keep using WSL:

```bash
./scripts/build_release_ipa.sh
```

## Pinned versions

Edit [`.github/xtool-version.env`](../.github/xtool-version.env):

| Variable | Current | Purpose |
|----------|---------|---------|
| `XTOOL_VERSION` | 1.17.0 | [xtool release](https://github.com/xtool-org/xtool/releases) AppImage |
| `SWIFT_VERSION` | 6.2 | Host Swift (matches [`Package.swift`](../Package.swift)) |

After bumping `XTOOL_VERSION`, clear or update the Actions cache for `darwin-sdk-*` if SDK install fails.

## Repo requirements for CI

- [`Resources/AppIcon.png`](../Resources/AppIcon.png) must be committed (`xtool.yml` → `iconPath`)
- [`AppSupport/SandStories-App-Info.plist`](../AppSupport/SandStories-App-Info.plist) privacy keys are merged in [`scripts/merge_privacy_into_app.sh`](../scripts/merge_privacy_into_app.sh)

## Signing and TestFlight (later)

This workflow **builds and packages** an IPA. It does **not** require Apple secrets for compile-only SideStore installs.

For **TestFlight** or App Store distribution later:

- Switch to a **`macos-*`** runner (or keep xtool on macOS)
- Add Apple certificates / App Store Connect API secrets
- Add a separate workflow step for upload

See [README Phase 3](../README.md) for storage-format benchmarks; CI here is independent of that research.

## Troubleshooting

| Failure | Fix |
|---------|-----|
| `No Darwin Swift SDK` | Complete [One-time bootstrap](#one-time-bootstrap-darwin-swift-sdk) |
| `missing Resources/AppIcon.png` | Commit the app icon under `Resources/` |
| `No valid Swift SDK bundles` | Re-pack SDK with `ci-pack-darwin-sdk.sh` after local `xtool setup` |
| Build OK locally, CI fails | Check pinned `XTOOL_VERSION` / `SWIFT_VERSION` match your working machine |
