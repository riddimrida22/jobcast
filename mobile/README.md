# JobBreak mobile (Capacitor)

Native iOS + Android shells that load the live jobbreak.ai experience and add
native push notifications for Monitor outlook alerts. Subscriptions stay on the
web (Stripe) to avoid app-store commission.

## Build (once prerequisites are installed)
Prereqs: Node (have it), a JDK + Android Studio (for Android), a Mac + Xcode (for iOS).

    cd mobile
    npm install
    npx cap add android        # creates the android/ project
    npx cap sync
    npx cap open android       # build + run / upload to Google Play

For iOS, do the same with ios (needs a Mac, or a cloud Mac build such as Codemagic).

## Push notifications
@capacitor/push-notifications is installed. Wiring: a Firebase (FCM) project for
Android, APNs for iOS, device token registered to the JobBreak alert store, and the
alerter sends a push alongside the email. (Next step after the shells build.)
