# MigrateKit Serverless Backend Template

This directory contains the placeholder configuration and function code for a serverless backend. If you want to move away from static client-side license generation, you can use these serverless templates to process verified payments and email licenses automatically.

## How it works

```
   PayPal Payment Button (Client)
                 │
                 ▼
     Process Payment (PayPal)
                 │
        [Sends Webhook POST]
                 ▼
    Netlify/Vercel Serverless Function (This folder)
                 │
        [Generates License Key]
                 ▼
       Save Key to DB & Email Key
```

---

## Netlify Deployment Steps (Zero-Cost Hosting)

1. **Setup Netlify**: Create a free account on [Netlify](https://www.netlify.com/).
2. **Link Repo**: Link your GitHub repository `Jamezboi/MigrateKit` to Netlify.
3. **Configure Build Settings**:
   - **Base directory**: `serverless-backend`
   - **Build command**: (Leave blank)
   - **Publish directory**: (Leave blank or point to static assets)
   - Netlify will automatically discover the `netlify/functions/` folder.
4. **Deploy**: Trigger deployment. Netlify will expose your webhook function at:
   `https://<your-app-name>.netlify.app/.netlify/functions/paypal-webhook`

---

## PayPal Webhook Integration

1. Go to your [PayPal Developer Dashboard](https://developer.paypal.com/dashboard).
2. Under **My Apps & Credentials**, select your App (Sandbox or Live).
3. Scroll down to the **Webhooks** section and click **Add Webhook**.
4. Enter the Netlify function URL:
   `https://<your-app-name>.netlify.app/.netlify/functions/paypal-webhook`
5. Select the event type: **Payment capture completed** (`PAYMENT.CAPTURE.COMPLETED`).
6. Click **Save**. PayPal will now send a JSON POST body to your serverless backend whenever a successful payment occurs.
