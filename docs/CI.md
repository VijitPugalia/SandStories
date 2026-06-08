# Continuous integration (GitHub Actions)

Build SandStories on **GitHub-hosted macOS** (no local Mac required). Each successful run on `main` produces a downloadable **`SandStories.ipa`** artifact.

Workflow: [`.github/workflows/build-ipa.yml`](../.github/workflows/build-ipa.yml)

## What runs on every push

1. Use the runner’s **Xcode / iOS SDK** (preinstalled on `macos-15`)
2. Install **xtool** from the pinned release zip ([`scripts/ci-setup-xtool-macos.sh`](../scripts/ci-setup-xtool-macos.sh))
3. Run [`scripts/build_release_ipa.sh`](../scripts/build_release_ipa.sh)
4. Upload `xtool/SandStories.ipa` as a workflow artifact

No `DARWIN_SDK_TARBALL_URL` secret is required for this workflow.

**Pull requests** also build and upload a short-lived IPA artifact (7 days).  
**Pushes to `main`** and **manual runs** keep artifacts for 30 days.

## Download the IPA

1. Open your repo on GitHub → **Actions**
2. Click the latest **Build IPA** run
3. Under **Artifacts**, download **SandStories-ipa**
4. Install on your iPhone with **SideStore** (same as a local build)

No Mac required for this step.

## Alternative: Ubuntu + xtool (advanced)

To use cheaper Linux runners instead of `macos-15`, you must supply Apple’s iOS SDK yourself:

1. On WSL after `xtool setup` with `Xcode_16.3.xip`: `bash scripts/ci-pack-darwin-sdk.sh ~/darwin-sdk.tar.gz`
2. Host the tarball at a private URL
3. Change the workflow `runs-on` to `ubuntu-24.04` and use [`scripts/ci-setup-xtool.sh`](../scripts/ci-setup-xtool.sh)
4. Add secret `DARWIN_SDK_TARBALL_URL`

### Local WSL build (no CI)

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
| `xtool.app.zip` download fails | Check [xtool releases](https://github.com/xtool-org/xtool/releases) and `XTOOL_VERSION` in `.github/xtool-version.env` |
| `missing Resources/AppIcon.png` | Commit the app icon under `Resources/` |
| `xcrun -sdk iphoneos` fails | GitHub `macos-15` image issue — try `macos-14` in the workflow |
| Build OK on WSL, CI fails | macOS CI uses Xcode SDK; WSL uses xtool cross-compile — both are supported |
