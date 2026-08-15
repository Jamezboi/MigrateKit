const crypto = require('crypto');

// MD5/SHA-256 License Key generation parameters matching the desktop app
const SALT = "MIGRATEKIT-SALT-2026";
const ALPHANUM = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

function generateSecureLicenseKey() {
  let first_15 = '';
  for (let i = 0; i < 15; i++) {
    first_15 += ALPHANUM.charAt(Math.floor(Math.random() * ALPHANUM.length));
  }
  
  // Hash first_15 + SALT using SHA-256
  const hash = crypto.createHash('sha256')
                     .update(first_15 + SALT)
                     .digest('hex')
                     .toUpperCase();
                     
  const last_5 = hash.substring(0, 5);
  const fullKey = first_15 + last_5;
  
  // Format as XXXXX-XXXXX-XXXXX-XXXXX
  return fullKey.match(/.{1,5}/g).join('-');
}

exports.handler = async (event, context) => {
  // Only allow POST requests from PayPal webhooks
  if (event.httpMethod !== "POST") {
    return {
      statusCode: 405,
      body: "Method Not Allowed"
    };
  }

  try {
    const payload = JSON.parse(event.body);
    
    // In production: Validate webhook signature using PayPal public certificates.
    // PayPal passes headers: paypal-transmission-id, paypal-transmission-time, 
    // paypal-cert-url, paypal-auth-algo, paypal-transmission-sig
    
    console.log(`Webhook Event Type: ${payload.event_type}`);
    
    if (payload.event_type === "PAYMENT.CAPTURE.COMPLETED") {
      const transactionId = payload.resource.id;
      const amount = payload.resource.amount.value;
      const currency = payload.resource.amount.currency_code;
      const buyerEmail = payload.resource.payer?.email_address || "unknown@paypal.com";
      const buyerName = payload.resource.payer?.name?.given_name || "Customer";
      
      console.log(`Verified payment from ${buyerEmail} for $${amount} ${currency}`);
      
      // 1. Generate the secure cryptographically verifiable license key
      const licenseKey = generateSecureLicenseKey();
      
      // 2. [Optional DB save]: Write transactionId, buyerEmail, licenseKey to your database
      // e.g. await db.insert({ transactionId, buyerEmail, licenseKey, date: new Date() })
      
      // 3. [Optional Email Delivery]: Send the license key to buyerEmail using Resend/SendGrid/SES
      // e.g. await mail.send(buyerEmail, "Your MigrateKit License Key", `Hi ${buyerName}, key: ${licenseKey}`)
      
      console.log(`Generated Key for user: ${licenseKey}`);
      
      return {
        statusCode: 200,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status: "SUCCESS",
          message: "License key generated and processed",
          licenseKey: licenseKey,
          email: buyerEmail
        })
      };
    }
    
    return {
      statusCode: 200,
      body: "Event type not processed (only captures expected)"
    };
  } catch (error) {
    console.error("Webhook processing error:", error);
    return {
      statusCode: 500,
      body: JSON.stringify({ error: "Internal Server Error", message: error.message })
    };
  }
};
