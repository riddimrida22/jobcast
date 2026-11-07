# JobBreak mobile (iOS + Android)

A thin native shell that wraps the JobBreak web app with [Capacitor](https://capacitorjs.com).
One codebase, three targets: the web app stays primary, and these native apps load it and add
native features (push, share, splash). The web work you ship is the app.

## How it works

`capacitor.config.json` sets `server.url` to the hosted site, so the native app loads the live
JobBreak web app in a WebView. There is nothing to rebuild on the native side when the web app
changes. The `www/` folder is a lightweight splash shown while the site loads (Capacitor requires
a `webDir`).

## Prerequisites

- Node 18+ and npm (already used here).
- Android: Android Studio (builds on Windows, macOS, or Linux).
- iOS: a Mac with Xcode and CocoaPods (iOS apps can only be built on macOS). Day-to-day web work
  stays on Windows; use the Mac only for the iOS build and submit steps.

## First-time setup

```bash
cd mobile
npm install
npx cap add android      # generates the android/ project (any OS)
npx cap add ios          # generates the ios/ project (run the build on a Mac)
npx cap sync             # copies config + plugins into the native projects
```

Then open and run:

```bash
npx cap open android     # Android Studio -> run on a device/emulator
npx cap open ios         # Xcode (on the Mac) -> run on a simulator/device
```

## After any change to config or plugins

```bash
npx cap sync
```

## Before the first store submission (do these once)

1. **App ID** — `appId` is currently `pc.aquatechpc.jobbreak` (a domain you control). It is permanent
   once published; change it here before the first submit if you want a `jobbreak.app` identity.
2. **Production URL** — point `server.url` at the public domain (e.g. `https://jobbreak.app`), not the
   gated Render preview, and make sure the preview login gate is off for production.
3. **App icons + splash** — replace the placeholder with real icons (the `@capacitor/assets` tool
   generates every size from one 1024x1024 source image).
4. **Push notifications** — wire `@capacitor/push-notifications` to your provider (APNs for iOS, FCM
   for Android). This is the native feature that makes the app more than a web wrapper and gives you
   the "your job's outlook changed" alert from the email-signup idea.
5. **Apple review note (Guideline 4.2)** — Apple can reject apps that are only a repackaged website.
   The push notifications, native share, and offline splash are what make this a legitimate app;
   make sure at least push is live before submitting to iOS.

## Accounts needed to publish

- Apple Developer Program: $99/year.
- Google Play Console: $25 one-time.

## Native features already declared (plugins)

- `@capacitor/push-notifications` - "your outlook changed" alerts (wire to APNs/FCM).
- `@capacitor/share` - native share sheet for the result card.
- `@capacitor/splash-screen` - branded launch screen.
- `@capacitor/app` - lifecycle + deep-link hooks.

The native platform folders (`ios/`, `android/`) are git-ignored; regenerate them with
`npx cap add` on any machine. Everything needed to recreate them lives in this folder.
