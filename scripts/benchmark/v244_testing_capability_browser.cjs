#!/usr/bin/env node
"use strict";

const fs = require("fs");
const crypto = require("crypto");
const path = require("path");
const { chromium } = require("playwright");

const baseUrl = process.argv[2];
const evidenceDir = process.argv[3];
const runId = process.argv[4];
const chromePath = process.argv[5] || undefined;

if (!baseUrl || !evidenceDir || !runId) {
  process.stderr.write("usage: browser.cjs <base-url> <evidence-dir> <run-id> [chrome-path]\n");
  process.exit(2);
}
fs.mkdirSync(evidenceDir, { recursive: true });

async function openPage(browser, caseId) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  await context.tracing.start({
    screenshots: true,
    snapshots: true,
    sources: false,
    title: `GT-BENCH-005:${runId}:${caseId}`
  });
  const page = await context.newPage();
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  return { context, page };
}

async function login(page) {
  await page.click("#login");
  await page.waitForFunction(
    () => document.querySelector("#auth-state").textContent === "signed in",
    null,
    { timeout: 3000 }
  );
  await waitForOrderSync(page);
}

async function waitForOrderSync(page) {
  await page.waitForFunction(
    () => document.querySelector("#order-count").dataset.synced === "true",
    null,
    { timeout: 5000 }
  );
}

async function waitForCreateIdle(page) {
  await page.waitForFunction(
    () => (
      document.querySelector("#create-order").dataset.pending === "0"
      && document.querySelector("#order-count").dataset.synced === "true"
    ),
    null,
    { timeout: 5000 }
  );
}

async function count(page) {
  return Number(await page.textContent("#order-count"));
}

async function screenshot(page, context, name) {
  const target = path.join(evidenceDir, `${name}.png`);
  const trace = path.join(evidenceDir, `${name}.trace.zip`);
  await page.screenshot({ path: target, fullPage: true });
  const screenshotSha256 = crypto
    .createHash("sha256")
    .update(fs.readFileSync(target))
    .digest("hex");
  const marker = {
    schema_version: "goal-teams-browser-trace-marker-v2.44",
    run_id: runId,
    case_id: name,
    screenshot_sha256: screenshotSha256,
    page_url: page.url()
  };
  await page.evaluate(
    (value) => console.info(`GT_BENCH_BROWSER_PROVENANCE ${JSON.stringify(value)}`),
    marker
  );
  await context.tracing.stop({ path: trace });
  return { screenshot: target, browser_trace: trace };
}

async function sessionCase(browser) {
  const caseId = "E2E-SESSION-001";
  const { context, page } = await openPage(browser, caseId);
  try {
    await login(page);
    await page.reload({ waitUntil: "networkidle" });
    await waitForOrderSync(page);
    const authState = await page.textContent("#auth-state");
    const artifacts = await screenshot(page, context, caseId);
    return {
      case_id: caseId,
      layer: "e2e",
      status: authState === "signed in" ? "passed" : "failed",
      behavior_observed: true,
      evidence: { auth_state_after_reload: authState, ...artifacts }
    };
  } finally {
    await context.close();
  }
}

async function doubleClickCase(browser) {
  const caseId = "E2E-DOUBLE-CLICK-001";
  const { context, page } = await openPage(browser, caseId);
  try {
    await login(page);
    const before = await count(page);
    await page.evaluate(() => {
      document.querySelector("#create-order").click();
      document.querySelector("#create-order").click();
    });
    await waitForCreateIdle(page);
    const after = await count(page);
    const artifacts = await screenshot(page, context, caseId);
    return {
      case_id: caseId,
      layer: "e2e",
      status: after - before === 1 ? "passed" : "failed",
      behavior_observed: true,
      evidence: { count_before: before, count_after: after, delta: after - before, ...artifacts }
    };
  } finally {
    await context.close();
  }
}

async function refreshCase(browser) {
  const caseId = "E2E-REFRESH-001";
  const { context, page } = await openPage(browser, caseId);
  try {
    await login(page);
    await page.click("#create-order");
    await page.waitForFunction(
      () => document.querySelector("#status").textContent === "created",
      null,
      { timeout: 3000 }
    );
    await waitForCreateIdle(page);
    const beforeReload = await count(page);
    await page.reload({ waitUntil: "networkidle" });
    await waitForOrderSync(page);
    await page.waitForTimeout(150);
    const afterReload = await count(page);
    const artifacts = await screenshot(page, context, caseId);
    return {
      case_id: caseId,
      layer: "e2e",
      status: beforeReload > 0 && afterReload === beforeReload ? "passed" : "failed",
      behavior_observed: true,
      evidence: { count_before_reload: beforeReload, count_after_reload: afterReload, ...artifacts }
    };
  } finally {
    await context.close();
  }
}

async function recoveryCase(browser) {
  const caseId = "E2E-RECOVERY-001";
  const { context, page } = await openPage(browser, caseId);
  try {
    await login(page);
    const before = await count(page);
    await page.evaluate(async () => {
      await fetch("/api/test/fail-next", {
        method: "POST",
        headers: { Authorization: "Bearer gt-bench-session" }
      });
    });
    await page.click("#create-order");
    await page.waitForFunction(
      () => document.querySelector("#status").textContent.startsWith("error:"),
      null,
      { timeout: 3000 }
    );
    await waitForCreateIdle(page);
    const retryVisible = await page.isVisible("#retry");
    if (retryVisible) {
      await page.click("#retry");
      await page.waitForFunction(
        () => document.querySelector("#status").textContent === "created",
        null,
        { timeout: 3000 }
      );
      await waitForCreateIdle(page);
    }
    await page.waitForTimeout(100);
    const after = await count(page);
    const artifacts = await screenshot(page, context, caseId);
    return {
      case_id: caseId,
      layer: "e2e",
      status: retryVisible && after - before === 1 ? "passed" : "failed",
      behavior_observed: true,
      evidence: {
        retry_visible_after_failure: retryVisible,
        count_before: before,
        count_after: after,
        delta: after - before,
        ...artifacts
      }
    };
  } finally {
    await context.close();
  }
}

(async () => {
  const options = { headless: true };
  if (chromePath) options.executablePath = chromePath;
  const browser = await chromium.launch(options);
  try {
    const cases = [];
    for (const operation of [sessionCase, doubleClickCase, refreshCase, recoveryCase]) {
      try {
        cases.push(await operation(browser));
      } catch (error) {
        cases.push({
          case_id: {
            sessionCase: "E2E-SESSION-001",
            doubleClickCase: "E2E-DOUBLE-CLICK-001",
            refreshCase: "E2E-REFRESH-001",
            recoveryCase: "E2E-RECOVERY-001"
          }[operation.name],
          layer: "e2e",
          status: "failed",
          behavior_observed: true,
          evidence: { browser_error: String(error && error.message || error) }
        });
      }
    }
    process.stdout.write(JSON.stringify({
      runtime: { status: "executed", engine: "playwright-chromium", run_id: runId },
      cases
    }));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
});
