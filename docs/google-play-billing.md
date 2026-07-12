# Google Play Billing — setup & operations

OttoAI's Android app sells subscriptions through **Google Play Billing** (Play
policy requires it for in-app digital subscriptions). The app (expo-iap) owns
the purchase UI; our backend verifies every purchase token with Google and is
the single source of truth for entitlement, reusing the same
`activate_paid(provider="google_play")` core the web/Razorpay path uses.

```
App (expo-iap)                Backend                         Google
──────────────                ───────                         ──────
requestPurchase()  ───►  Play purchase sheet
   purchaseToken   ───►  POST /billing/google-play/verify
                              └─ subscriptionsv2.get ───►  verify token
                              └─ activate_paid(...)         (authoritative
                              └─ acknowledge  ───────────►   expiryTime/state)
renewals/cancels/refunds ◄─── RTDN (Pub/Sub push) ◄──────  lifecycle events
                          POST /billing/google-play/rtdn
```

## What the code already does

- **`POST /billing/google-play/verify`** (authenticated): the app calls this
  right after purchase with the `purchase_token`. The plan is derived from
  Google's response, never trusted from the client. Grants entitlement only if
  Google reports the subscription active, then acknowledges it.
- **`POST /billing/google-play/rtdn`**: Pub/Sub push endpoint for Real-Time
  Developer Notifications. Re-fetches authoritative state from Google and
  reconciles renewals (extend), cancellations (lapse at period end), and
  revoke/expiry (end now). Idempotent on the Pub/Sub `messageId` (lifecycle)
  and the order id (activations).
- Entitlement uses Google's authoritative `expiryTime` via the new
  `activate_paid(expires_at_override=...)` argument, so trials/grace/proration
  stay correct.

## One-time setup (you must do this — I can't)

### 1. Create the subscription products in Play Console
Play Console → **Monetize → Products → Subscriptions**. Create two products
whose IDs match the config defaults (or change both places):

| Plan    | Product ID (default)  | Base plan            |
|---------|-----------------------|----------------------|
| Monthly | `ottoai_pro_monthly`  | auto-renewing, P1M, ₹149 |
| Yearly  | `ottoai_pro_yearly`   | auto-renewing, P1Y, ₹1499 |

Give each an **active base plan** and activate the product. The client product
IDs live in `mobile-app/.../src/billing/googlePlay.ts` (`PRODUCT_IDS`); the
backend's live in `GOOGLE_PLAY_PRODUCT_MONTHLY` / `_YEARLY`.

> ⚠️ **Plan switching:** monthly and yearly are *separate products*, so the app
> currently starts a fresh purchase when a user changes plan — on Android that
> can leave two active subscriptions. Before enabling cross-plan switching,
> either (a) implement Play's replacement flow (pass the existing purchase
> token + a replacement mode to `requestPurchase`), or (b) model monthly/yearly
> as two **base plans under one product** and map `basePlanId → plan` on the
> backend. See `TODO(plan-switch)` in `SubscriptionContext`/`google_play_service`.

### 2. Service account for the Play Developer API
1. Play Console → **Setup → API access** → link/create a Google Cloud project.
2. Create a **service account** in Google Cloud, download its **JSON key**.
3. Back in Play Console → API access → grant that account access with at least
   **View financial data** and **Manage orders and subscriptions**.
4. Put the JSON into the backend env (single-line, or a file path):
   `GOOGLE_PLAY_SERVICE_ACCOUNT_JSON`.

### 3. Real-Time Developer Notifications (RTDN)
1. Google Cloud → **Pub/Sub** → create a topic, e.g. `play-rtdn`.
2. Grant `google-play-developer-notifications@system.gserviceaccount.com` the
   **Pub/Sub Publisher** role on that topic.
3. Play Console → **Monetization setup** → set the **Topic name** to that topic
   and enable real-time notifications.
4. Create a **push subscription** on the topic with endpoint:
   `https://<backend>/billing/google-play/rtdn?token=<GOOGLE_PLAY_RTDN_VERIFICATION_TOKEN>`
   Use the "Send test notification" button to confirm 200s arrive.

### 4. License testers (for testing without being charged)
Play Console → **Setup → License testing** → add tester Google accounts. Test
on an **internal testing track** build signed with the upload key.

## Required environment variables

Add these to the backend `.env` **and** on Render (see the deploy-split note):

```
GOOGLE_PLAY_PACKAGE_NAME=com.sahibdeepjwd.phagan
GOOGLE_PLAY_SERVICE_ACCOUNT_JSON={...single-line service-account JSON...}
GOOGLE_PLAY_PRODUCT_MONTHLY=ottoai_pro_monthly
GOOGLE_PLAY_PRODUCT_YEARLY=ottoai_pro_yearly
GOOGLE_PLAY_RTDN_VERIFICATION_TOKEN=<a long random string>
```

`google-api-python-client` and `google-auth` are in `requirements.txt`. Run the
DB migration (`alembic upgrade head` — the app does this on boot) to add
`users.google_play_purchase_token`.

## Mobile build note

expo-iap is autolinked; its `openiap-google` dependency resolves from
`mavenCentral()` (already in the Android project). The
`com.android.vending.BILLING` permission is added to `AndroidManifest.xml` by
hand (config plugins don't run here — native folders are checked in). **A new
dev-client / release build is required** — a JS-only OTA update won't include
the native billing module.

## Testing checklist

- [ ] Internal-track build installed on a device with a license-tester account.
- [ ] Buy monthly → app shows Pro; `payments` ledger has a `google_play`
      `subscription.purchased` row; `users.subscription_expires_at` matches
      Google's expiry.
- [ ] Play Console "Send test notification" → `/rtdn` returns 200.
- [ ] Let a renewal fire (test subscriptions renew fast) → entitlement extends,
      one new ledger row per order.
- [ ] Cancel in Play → status becomes `cancelled`, access remains until expiry.
- [ ] Refund/revoke in Play Console → access ends promptly (`mark_expired`).
- [ ] "Restore purchases" on the paywall re-grants Pro on a reinstalled app.
