import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const css = readFileSync(new URL('../src/assistant/assistant.css', import.meta.url), 'utf8')

test('desktop mobile backdrop is removed from the app grid', () => {
  assert.match(css, /\.va-app\s*>\s*\.va-mobile-backdrop\s*\{\s*display:none;/)
})

test('desktop shell pins sidebar and main to their intended grid columns', () => {
  assert.match(css, /\.va-sidebar\s*\{[^}]*grid-column:1;[^}]*grid-row:1;/s)
  assert.match(css, /\.va-main\s*\{[^}]*grid-column:2;[^}]*grid-row:1;/s)
})

test('mobile shell moves main back to the single grid column', () => {
  assert.match(css, /@media\(max-width:720px\)[^{]*\{[^}]*\.va-app\s*\{[^}]*grid-template-columns:minmax\(0,1fr\);[^}]*\}\s*\.va-main\s*\{[^}]*grid-column:1;[^}]*grid-row:1;/s)
})
