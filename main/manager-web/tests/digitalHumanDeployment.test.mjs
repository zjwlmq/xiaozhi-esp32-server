import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const repoRoot = new URL("../../../", import.meta.url);
const configUrl = new URL("main/digital-human/js/config/manager.js", repoRoot);
const configSource = await readFile(configUrl, "utf8");
const configModule = await import(
  `data:text/javascript;base64,${Buffer.from(configSource).toString("base64")}`
);

const remoteLocation = {
  protocol: "https:",
  hostname: "example.test",
  host: "example.test",
  port: "",
  origin: "https://example.test"
};

const localRuntimeLocation = {
  protocol: "http:",
  hostname: "127.0.0.1",
  host: "127.0.0.1:8006",
  port: "8006",
  origin: "http://127.0.0.1:8006"
};

test("server-hosted tester derives OTA from the current HTTPS origin", () => {
  assert.equal(
    configModule.getDefaultOtaUrl(remoteLocation),
    "https://example.test/xiaozhi/ota/"
  );
  assert.equal(configModule.getDefaultWakewordEnabled(remoteLocation), "false");
  assert.equal(configModule.getDefaultWakewordBridgeUrl(remoteLocation), "");
});

test("standalone Python runtime keeps its local OTA and wakeword bridge", () => {
  assert.equal(
    configModule.getDefaultOtaUrl(localRuntimeLocation),
    "http://127.0.0.1:8002/xiaozhi/ota/"
  );
  assert.equal(configModule.getDefaultWakewordEnabled(localRuntimeLocation), "true");
  assert.equal(
    configModule.getDefaultWakewordBridgeUrl(localRuntimeLocation),
    "ws://127.0.0.1:8006/wakeword-ws"
  );
});

test("web image and nginx expose the tester at a dedicated static route", async () => {
  const [dockerfile, nginx, html, app] = await Promise.all([
    readFile(new URL("Dockerfile-web", repoRoot), "utf8"),
    readFile(new URL("docs/docker/nginx.conf", repoRoot), "utf8"),
    readFile(new URL("main/digital-human/index.html", repoRoot), "utf8"),
    readFile(new URL("main/digital-human/js/app.js", repoRoot), "utf8")
  ]);

  assert.match(dockerfile, /\/usr\/share\/nginx\/html\/digital-human/);
  assert.match(nginx, /location \/digital-human\//);
  assert.match(nginx, /try_files \$uri \$uri\/ =404;/);
  assert.match(html, /<title>小智无硬件测试台<\/title>/);
  assert.doesNotMatch(html, /id="otaUrl" value="http:\/\/127\.0\.0\.1/);
  assert.match(app, /if \(wakewordEnabled\) \{\s*startWakewordBridgeListener\(\);/);
  assert.match(app, /void this\.checkMicrophoneAvailability\(\);/);
  assert.doesNotMatch(app, /await this\.checkMicrophoneAvailability\(\);/);
});
