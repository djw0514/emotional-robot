import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import ts from 'typescript';

const source = readFileSync(new URL('../apps/harmony/entry/src/main/ets/services/SseParser.ets', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ES2020 },
  reportDiagnostics: true,
});
assert.equal(compiled.diagnostics.length, 0);
const { SseParser } = await import('data:text/javascript;base64,' + Buffer.from(compiled.outputText).toString('base64'));

test('Chinese UTF-8 survives every possible split between bytes', () => {
  const text = 'event: token\ndata: {"text":"你好，小周🌱"}\n\n';
  const bytes = new TextEncoder().encode(text);
  for (let split = 0; split <= bytes.length; split++) {
    const events = [];
    const parser = new SseParser(event => events.push(event));
    const decoder = new TextDecoder('utf-8');
    parser.feed(decoder.decode(bytes.slice(0, split), { stream: true }));
    parser.feed(decoder.decode(bytes.slice(split), { stream: true }));
    parser.feed(decoder.decode());
    assert.equal(events.length, 1);
    assert.equal(JSON.parse(events[0].data).text, '你好，小周🌱');
  }
});

test('CRLF boundaries, comment heartbeat, and multiple data lines', () => {
  const events = [];
  const parser = new SseParser(event => events.push(event));
  for (const character of ': heartbeat\r\nevent: completed\r\ndata: one\r\ndata: two\r\n\r\n') {
    parser.feed(character);
  }
  assert.deepEqual(events, [{ event: 'completed', data: 'one\ntwo' }]);
});

test('incomplete events are not reported as complete', () => {
  const events = [];
  new SseParser(event => events.push(event)).feed('event: completed\ndata: {}\n');
  assert.equal(events.length, 0);
});

test('oversized incomplete frame is rejected', () => {
  assert.throws(() => new SseParser(() => {}).feed('x'.repeat(1048577)));
});
