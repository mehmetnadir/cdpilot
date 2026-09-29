# web-bot-auth

This example demonstrates Web Bot Auth HTTP Message Signatures (RFC 9421) using the RFC 9421 Ed25519 TEST key.
`launch --bot-auth` transparently signs outgoing HTTP requests, allowing Cloudflare to verify the bot identity.

## Commands

```bash
cdpilot bot-auth status
cdpilot bot-auth directory --headers --authority example.com
cdpilot launch --bot-auth
cdpilot go https://http-message-signatures-example.research.cloudflare.com/
cdpilot content
cdpilot shot output/screenshot.png
cdpilot stop
```

## Captured Output

```text
$ cdpilot bot-auth status
Bot Auth: configured
  agent URL : https://http-message-signatures-example.research.cloudflare.com
  keyid     : poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U
  format    : Signature-Agent legacy
  directory : https://http-message-signatures-example.research.cloudflare.com/.well-known/http-message-signatures-directory
  bot-auth: off (port 59855)
$ cdpilot bot-auth directory --headers --authority example.com
cdpilot: serve the body above at https://example.com/.well-known/http-message-signatures-directory with these headers; the signature expires in 86400 s (--ttl), then run this again
Content-Type: application/http-message-signatures-directory+json
Signature-Input: sig1=("@authority";req);created=1790638559;keyid="poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U";alg="ed25519";expires=1790724959;nonce="4eq0VhUpQSmjoRPuQBNCqPoPDrM8rUTxlPywUwODd7eSl+R0oxYma8rH6N9JnoKTpECOzyx7cAEIZZfPnmsx1Q==";tag="http-message-signatures-directory"
Signature: sig1=:wZrjALEe816wa+Pk7l/s4KuFMjGytgwylhQDu+HmFbDbsePZfzePnMv/TMyCIvkmlHfGVXCy8cBWw7Wx+RWcAQ==:

{
  "keys": [
    {
      "kty": "OKP",
      "crv": "Ed25519",
      "kid": "poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U",
      "x": "JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs",
      "use": "sig"
    }
  ]
}
$ cdpilot launch --bot-auth

  cdpilot v0.9.4 — Pre-flight Check
  ───────────────────────────────────

  ✓ Python 3.14.7
  ✓ websockets
  ✓ Brave Browser (/Applications/Brave Browser.app/Contents/MacOS/Brave Browser)

  Ready!

Launching browser (isolated session, port 59855) [web-bot-auth-f45e65]...
  Mode: headless
  Idle close: off (launch --idle-close <min> or CDPILOT_IDLE_CLOSE=<min> turns it on)
CDP ready! (port 59855) [web-bot-auth-f45e65]
  Bot Auth: signing every request as https://http-message-signatures-example.research.cloudflare.com (keyid poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U, Signature-Agent legacy)
$ cdpilot go https://http-message-signatures-example.research.cloudflare.com/
Identify Bots with HTTP Message Signatures
You successfully authenticated as owning the test public key

HTTP Message Signatures are a mechanism to create, encode, and verify signatures over components of an HTTP message. They are standardised by the IETF in RFC 9421. This website validates the presence of such signature as defined in draft-meunier-web-bot-auth-architecture.

This website checks for an Ed25519 signature on incoming request. They should be signed by a test public key defined in Appendix B.1.4 of RFC 9421.

Why do platforms and websites need this?

As a platform provider, I would like to ensure websites are able to identify requests originating from my service. At the moment, I share IP ranges, but this is long to deploy, cumbersome to maintain, and costly, especially with the multiplication of services, and the need to localise outgoing traffic with a forward proxy. It's even more pressing as I onboard multiple companies on my platform that need to have their own identity. And user agent headers do not have any integrity protection.

It's time for websites to know who's calling, and for platforms to prove it.

How to retrieve the public key used by this website

We define a key directory accessible under /.well-known/http-message-signatures-directory The directory looks as follow

{
  "keys": [
    {
      "kid":"poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U",
      "kty":"OKP",
      "crv":"Ed25519",
      "x":"JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs",
      "nbf": 1743465600000
    }
  ]
}
      

Parameters are defined as follow:

keys: an array of serialised JSON Web Key defined by RFC 7517
kid: JWK Thumbprint as defined in RFC 7638
nbf: start of the validity of the public key as a unix timestamp in milliseconds defined by RFC 7519
exp: end of the validity of the public key as a unix timestamp in milliseconds defined by RFC 7519
...jwk: JWK public cryptographic material
purpose: represents what a signature means. Examples could be the draft for Short usage preference proposed.

It's hard to debug. How can this website help?

Use the debug page to validate key directories and signature headers.

I have comments and want to contribute. Where do I go?

First off, this is fantastic news!

To contribute to this website, you can go to cloudflareresearch/web-bot-auth.

To contribute to the standard discussion, the current draft is hosted on thibmeu/http-message-signatures-directory, and is being discussed on web-bot-auth IETF mailing list.
$ cdpilot content
Identify Bots with HTTP Message Signatures
You successfully authenticated as owning the test public key

HTTP Message Signatures are a mechanism to create, encode, and verify signatures over components of an HTTP message. They are standardised by the IETF in RFC 9421. This website validates the presence of such signature as defined in draft-meunier-web-bot-auth-architecture.

This website checks for an Ed25519 signature on incoming request. They should be signed by a test public key defined in Appendix B.1.4 of RFC 9421.

Why do platforms and websites need this?

As a platform provider, I would like to ensure websites are able to identify requests originating from my service. At the moment, I share IP ranges, but this is long to deploy, cumbersome to maintain, and costly, especially with the multiplication of services, and the need to localise outgoing traffic with a forward proxy. It's even more pressing as I onboard multiple companies on my platform that need to have their own identity. And user agent headers do not have any integrity protection.

It's time for websites to know who's calling, and for platforms to prove it.

How to retrieve the public key used by this website

We define a key directory accessible under /.well-known/http-message-signatures-directory The directory looks as follow

{
  "keys": [
    {
      "kid":"poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U",
      "kty":"OKP",
      "crv":"Ed25519",
      "x":"JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs",
      "nbf": 1743465600000
    }
  ]
}
      

Parameters are defined as follow:

keys: an array of serialised JSON Web Key defined by RFC 7517
kid: JWK Thumbprint as defined in RFC 7638
nbf: start of the validity of the public key as a unix timestamp in milliseconds defined by RFC 7519
exp: end of the validity of the public key as a unix timestamp in milliseconds defined by RFC 7519
...jwk: JWK public cryptographic material
purpose: represents what a signature means. Examples could be the draft for Short usage preference proposed.

It's hard to debug. How can this website help?

Use the debug page to validate key directories and signature headers.

I have comments and want to contribute. Where do I go?

First off, this is fantastic news!

To contribute to this website, you can go to cloudflareresearch/web-bot-auth.

To contribute to the standard discussion, the current draft is hosted on thibmeu/http-message-signatures-directory, and is being discussed on web-bot-auth IETF mailing list.
$ cdpilot shot output/screenshot.png
output/screenshot.png (50.9KB)
$ cdpilot stop
  Closed via CDP Browser.close.
Browser stopped (port 59855).
```
