# M-PESA (Daraja) setup

This project supports initiating payments via **STK Push** and receiving the **callback** to mark a session as paid.

## Environment variables

This project auto-loads a `.env` file from the project root (see `.env.example`). You can also set these environment variables directly in your shell/server:

- `DJANGO_ALLOWED_HOSTS` (comma-separated): include your ngrok hostname (e.g. `xxxx.ngrok-free.app,localhost,127.0.0.1`)
- `DJANGO_CSRF_TRUSTED_ORIGINS` (comma-separated): include your ngrok origin (e.g. `https://xxxx.ngrok-free.app`)
- `MPESA_ENV`: `sandbox` or `production`
- `MPESA_CONSUMER_KEY`
- `MPESA_CONSUMER_SECRET`
- `MPESA_SHORTCODE` (paybill/till shortcode)
- `MPESA_PASSKEY` (for STK push)
- `MPESA_CALLBACK_URL` (public HTTPS URL that Daraja can reach)
- `MPESA_TRANSACTION_TYPE` (optional): `CustomerPayBillOnline` (paybill) or `CustomerBuyGoodsOnline` (till)

### PowerShell example (local)

```powershell
$env:DJANGO_ALLOWED_HOSTS="xxxx.ngrok-free.app,localhost,127.0.0.1"
$env:DJANGO_CSRF_TRUSTED_ORIGINS="https://xxxx.ngrok-free.app"
$env:MPESA_ENV="sandbox"
$env:MPESA_CONSUMER_KEY="..."
$env:MPESA_CONSUMER_SECRET="..."
$env:MPESA_SHORTCODE="174379"
$env:MPESA_PASSKEY="..."
$env:MPESA_CALLBACK_URL="https://xxxx.ngrok-free.app/payments/mpesa/callback/"
```

Do not commit keys/secrets to git.

## Callback endpoint

- Callback URL path in Django: `payments/mpesa/callback/`
- Example: `https://your-domain.example/payments/mpesa/callback/`

## How it works (high level)

- Patient/reception opens `payments/mpesa/<session_id>/` and submits a phone number.
- System sends an STK push prompt to the phone.
- Daraja calls back to `payments/mpesa/callback/`.
- On success, Django updates:
  - `clinic.PaymentTransaction` (stores receipt + raw callback)
  - `clinic.SessionRecord` (`payment_status=paid`, `payment_method=M-PESA`)

## Manual confirmation (paybill/till at reception)

Reception can mark a session as paid using:

- `POST reception/session/<session_id>/mpesa/manual/`

This creates a `PaymentTransaction` with a receipt number and marks the session as paid.
