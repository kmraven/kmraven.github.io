import { createPrivateKey, sign } from "node:crypto";
import { readFileSync } from "node:fs";

const [teamId, keyId, keyFile] = process.argv.slice(2);
const validId = /^[A-Z0-9]{10}$/;
if (!validId.test(teamId ?? "") || !validId.test(keyId ?? "") || !keyFile || process.argv.length !== 5) {
  console.error("Usage: node scripts/music-token.mjs TEAM_ID KEY_ID /path/to/AuthKey.p8");
  process.exit(1);
}
if (process.stdout.isTTY) {
  console.error("Capture the token using shell command substitution to keep it off screen.");
  process.exit(1);
}

function encode(value) {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

try {
  const key = createPrivateKey(readFileSync(keyFile));
  if (key.asymmetricKeyType !== "ec" || key.asymmetricKeyDetails?.namedCurve !== "prime256v1") {
    throw new Error("Invalid key type");
  }
  const iat = Math.floor(Date.now() / 1000);
  const header = encode({ alg: "ES256", kid: keyId });
  const payload = encode({ iss: teamId, iat, exp: iat + 12 * 60 * 60 });
  const message = header + "." + payload;
  const signature = sign("sha256", Buffer.from(message), { key, dsaEncoding: "ieee-p1363" });
  process.stdout.write(message + "." + signature.toString("base64url") + "\n");
} catch {
  console.error("Could not sign the token. Check your MusicKit P-256 private key file.");
  process.exitCode = 1;
}
