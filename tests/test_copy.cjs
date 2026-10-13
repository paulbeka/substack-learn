const { test } = require("node:test");
const assert = require("node:assert/strict");
require("../src/french_bot/static/dashboard.js");
const { copyArticle } = globalThis.FrenchDashboard;
const article = {
  innerHTML: "<h1>Bonjour</h1><h2>Vocabulary</h2><p><strong>Grammar</strong></p><ol><li>Question</li></ol><table><tr><td>café</td></tr></table>",
  innerText: "Bonjour\nVocabulary\nGrammar\nQuestion\ncafé"
};

test("writes rich HTML and plain text, preserving article structure", async () => {
  let received;
  const env = { isSecureContext: true, Blob,
    ClipboardItem: class { constructor(types) { this.types = types; } },
    navigator: { clipboard: { write: async items => { received = items; } } }
  };
  assert.match(await copyArticle(article, env), /Copied with formatting/);
  assert.equal(received.length, 1);
  assert.equal(await received[0].types["text/html"].text(), article.innerHTML);
  assert.equal(await received[0].types["text/plain"].text(), article.innerText);
});

function legacyEnv(success) {
  let handler, selected = false, removed = false;
  const types = {};
  const doc = {
    createRange: () => ({ selectNodeContents: value => assert.equal(value, article) }),
    getSelection: () => ({ removeAllRanges: () => {}, addRange: () => { selected = true; } }),
    addEventListener: (name, callback) => { handler = callback; },
    removeEventListener: () => { removed = true; },
    execCommand: () => {
      if (success) handler({ clipboardData: { setData: (type, data) => { types[type] = data; } }, preventDefault: () => {} });
      return success;
    }
  };
  return { env: { isSecureContext: false, navigator: {}, document: doc }, types,
    selected: () => selected, removed: () => removed };
}

test("legacy copy preserves both formats and removes its event handler", async () => {
  const legacy = legacyEnv(true);
  assert.match(await copyArticle(article, legacy.env), /Copied with formatting/);
  assert.equal(legacy.types["text/html"], article.innerHTML);
  assert.equal(legacy.types["text/plain"], article.innerText);
  assert.ok(legacy.removed());
});

test("denied clipboard permission falls back to selected article without false success", async () => {
  const legacy = legacyEnv(false);
  legacy.env.isSecureContext = true;
  legacy.env.Blob = Blob;
  legacy.env.ClipboardItem = class {};
  legacy.env.navigator = { clipboard: { write: async () => { throw new Error("denied"); } } };
  assert.match(await copyArticle(article, legacy.env), /article is selected/);
  assert.ok(legacy.selected() && legacy.removed());
});
