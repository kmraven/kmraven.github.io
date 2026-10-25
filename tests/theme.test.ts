import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

// Execute the shipped initialization and toggle scripts against a small browser stub.
const layout = readFileSync(new URL('../src/layouts/SiteLayout.astro', import.meta.url), 'utf8');
const component = readFileSync(new URL('../src/components/ThemeToggle.astro', import.meta.url), 'utf8');
const initialScript = layout.match(/<script is:inline>([\s\S]*?)<\/script>/)![1];
const toggleScript = ts.transpileModule(component.match(/<script>([\s\S]*?)<\/script>/)![1], {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
}).outputText;

function browser({ dark = false, saved = null, blocked = false }: { dark?: boolean; saved?: string | null; blocked?: boolean } = {}) {
  const root = { dataset: {} as Record<string, string> };
  const attributes: Record<string, string> = {};
  const listeners: Record<string, (event?: unknown) => void> = {};
  const button = {
    dataset: { lightLabel: 'Switch to light theme', darkLabel: 'Switch to dark theme' }, hidden: true, title: '',
    setAttribute: (key: string, value: string) => { attributes[key] = value; },
    addEventListener: (key: string, callback: () => void) => { listeners[key] = callback; },
  };
  let chromeColor = '';
  let stored = saved;
  const media = { matches: dark, addEventListener: (_key: string, callback: () => void) => { listeners.system = callback; } };
  const env = {
    document: {
      documentElement: root,
      querySelector: (selector: string) => selector === '[data-theme-toggle]' ? button : {
        setAttribute: (_key: string, value: string) => { chromeColor = value; },
      },
    },
    window: {
      matchMedia: () => media,
      addEventListener: (key: string, callback: (event: unknown) => void) => { listeners[key] = callback; },
    },
    localStorage: {
      getItem: () => { if (blocked) throw new Error('Storage denied'); return stored; },
      setItem: (_key: string, value: string) => { if (blocked) throw new Error('Storage denied'); stored = value; },
    },
  };
  runInNewContext(initialScript, env);
  const initialTheme = root.dataset.theme;
  const initialColor = chromeColor;
  runInNewContext(toggleScript, env);
  return { root, attributes, button, media, listeners, initialTheme, initialColor, stored: () => stored };
}

test('first visit follows the system without saving an automatic preference', () => {
  for (const dark of [true, false]) {
    const page = browser({ dark });
    assert.equal(page.initialTheme, undefined);
    assert.equal(page.initialColor, dark ? '#171b20' : '#ffffff');
    assert.equal(page.attributes['aria-label'], dark ? 'Switch to light theme' : 'Switch to dark theme');
    assert.equal(page.stored(), null);
    assert.equal(page.button.hidden, false);
  }
});

test('a saved selection overrides the system before rendering and can be toggled', () => {
  const page = browser({ dark: true, saved: 'light' });
  assert.equal(page.initialTheme, 'light');
  assert.equal(page.initialColor, '#ffffff');
  page.listeners.click();
  assert.equal(page.root.dataset.theme, 'dark');
  assert.equal(page.stored(), 'dark');
  assert.equal(page.attributes['aria-label'], 'Switch to light theme');
});

test('blocked storage does not break initial rendering or manual switching', () => {
  const page = browser({ dark: true, blocked: true });
  page.listeners.click();
  assert.equal(page.root.dataset.theme, 'light');
  assert.equal(page.attributes['aria-label'], 'Switch to dark theme');
});

test('system changes follow the OS until a manual selection is made', () => {
  const page = browser();
  page.media.matches = true;
  page.listeners.system();
  assert.equal(page.attributes['aria-label'], 'Switch to light theme');
  page.listeners.click();
  page.listeners.system();
  assert.equal(page.root.dataset.theme, 'light');
  assert.equal(page.attributes['aria-label'], 'Switch to dark theme');
});

test('other tabs synchronize selections and removing a selection restores system behavior', () => {
  const page = browser({ dark: true, saved: 'light' });
  page.listeners.storage({ key: 'portal-theme', newValue: 'dark' });
  assert.equal(page.root.dataset.theme, 'dark');
  page.listeners.storage({ key: 'portal-theme', newValue: null });
  assert.equal(page.root.dataset.theme, undefined);
  assert.equal(page.attributes['aria-label'], 'Switch to light theme');
  assert.equal(browser({ dark: true, saved: 'invalid' }).initialTheme, undefined);
});
