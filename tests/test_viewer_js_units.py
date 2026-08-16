from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for viewer JS unit tests")
def test_viewer_split_js_core_units_run_without_playwright() -> None:
    script = textwrap.dedent(
        r"""
        const assert = require('assert/strict');
        const fs = require('fs');
        const path = require('path');
        const vm = require('vm');

        const repoRoot = process.argv.at(-1);
        const assetDir = path.join(repoRoot, 'claude_tap', 'viewer_assets');

        function classList() {
          return { add() {}, remove() {}, toggle() {}, contains() { return false; } };
        }

        function element() {
          return {
            style: {},
            dataset: {},
            classList: classList(),
            children: [],
            innerHTML: '',
            textContent: '',
            value: '',
            setAttribute() {},
            appendChild(child) { this.children.push(child); return child; },
            removeChild(child) { this.children = this.children.filter(item => item !== child); },
            addEventListener() {},
            querySelector() { return null; },
            querySelectorAll() { return []; },
            focus() {},
            select() {},
            setSelectionRange() {},
            remove() {},
          };
        }

        const context = {
          console,
          URLSearchParams,
          setTimeout() {},
          clearTimeout() {},
          requestAnimationFrame(callback) { if (typeof callback === 'function') callback(); return 1; },
          cancelAnimationFrame() {},
          window: {
            location: { search: '?embed=1&hideHeader=1&density=compact&theme=dark' },
            localStorage: { getItem() { return null; }, setItem() {} },
            matchMedia() { return { matches: false }; },
          },
          navigator: { language: 'en', clipboard: null },
          document: {
            documentElement: { dataset: {}, classList: classList() },
            body: element(),
            querySelector() { return element(); },
            querySelectorAll() { return []; },
            getElementById() { return element(); },
            createElement() { return element(); },
            addEventListener() {},
            removeEventListener() {},
            execCommand() { return false; },
          },
        };
        vm.createContext(context);

        for (const assetName of [
          'state.js',
          'responses.js',
          'lazy_loading.js',
          'i18n_ui.js',
          'live_bootstrap.js',
          'filters_search.js',
          'renderers.js',
          'diff.js',
          'utilities_mobile.js',
        ]) {
          const source = fs.readFileSync(path.join(assetDir, assetName), 'utf8');
          vm.runInContext(source, context, { filename: assetName });
        }

        const plain = value => JSON.parse(JSON.stringify(value));

        assert.deepEqual(plain(context.parseEmbedQueryOptions()), {
          enabled: true,
          hideHeader: true,
          hidePath: false,
          hideHistory: false,
          hideControls: false,
          compact: true,
          theme: 'dark',
        });

        assert.deepEqual(plain(context.turnSortSegments('1.02.beta')), [1, 2, 0]);
        assert.equal(context.compareTurns('1.10', '1.2') > 0, true);
        assert.equal(context.compareTurns('2', '10') < 0, true);

        assert.deepEqual(
          plain(context.lineDiff('alpha\nold\nsame', 'alpha\nnew\nsame')),
          [
            { type: 'ctx', text: 'alpha' },
            { type: 'change', oldText: 'old', newText: 'new' },
            { type: 'ctx', text: 'same' },
          ],
        );

        const events = [
          { event: 'response.created', data: { response: { id: 'resp_first' } } },
          {
            event: 'response.output_item.done',
            data: {
              output_index: 0,
              item: {
                id: 'item_first_tool',
                type: 'function_call',
                call_id: 'call_1',
                name: 'shell',
                arguments: '{"cmd":"pwd"}',
              },
            },
          },
          {
            event: 'response.completed',
            data: { response: { id: 'resp_first', output: [], usage: { output_tokens: 1 } } },
          },
          { event: 'response.created', data: { response: { id: 'resp_prefetch', generate: false } } },
          {
            event: 'response.completed',
            data: { response: { id: 'resp_prefetch', generate: false, usage: { output_tokens: 0 } } },
          },
        ];
        const groups = context.splitWebSocketResponseEvents(events);
        assert.equal(groups.length, 2);
        assert.equal(context.completedResponseFromEvents(groups[0].events).id, 'resp_first');
        assert.deepEqual(
          plain(groups.filter(group => context.isDisplayableWebSocketResponseGroup(group)).map(group => group.responseId)),
          ['resp_first'],
        );
        assert.deepEqual(plain(context.webSocketOutputMessages(groups[0].events)), [
          {
            type: 'message',
            role: 'assistant',
            content: [{
              type: 'tool_use',
              id: 'call_1',
              name: 'shell',
              input: { cmd: 'pwd' },
            }],
          },
        ]);

        assert.deepEqual(plain(context.normalizeDisplayContentBlocks([
          { type: 'input_text', text: 'hello' },
          { type: 'input_image', source: { media_type: 'image/png', data: 'base64-data' } },
          { type: 'tool_result', tool_use_id: 'call_1', content: 'ok' },
        ])), [
          { type: 'input_text', text: 'hello' },
          { type: 'input_image', source: { media_type: 'image/png', data: 'base64-data' } },
          { type: 'tool_result', tool_use_id: 'call_1', content: 'ok' },
        ]);

        assert.deepEqual(plain(context.getMessages({
          instructions: 'Be concise',
          input: [{ role: 'user', content: [{ type: 'input_text', text: 'Hi' }] }],
        })), [
          { role: 'developer', content: [{ type: 'text', text: 'Be concise' }] },
          { role: 'user', content: [{ type: 'input_text', text: 'Hi' }] },
        ]);

        assert.deepEqual(
          plain(context.getRequestTools({
            model: 'gpt-5.6-sol',
            input: [{
              type: 'additional_tools',
              role: 'developer',
              tools: [
                { name: 'exec', description: 'Run a command' },
                { name: 'wait' },
                { name: 'request_user_input' },
              ],
            }],
          }).map(tool => context.toolDisplayName(tool))),
          ['exec', 'wait', 'request_user_input'],
        );

        assert.deepEqual(
          plain(context.getRequestTools({
            tools: [{ name: 'exec' }],
            input: [{
              type: 'additional_tools',
              tools: [{ name: 'exec' }, { name: 'collaboration' }],
            }],
          }).map(tool => context.toolDisplayName(tool))),
          ['exec', 'collaboration'],
        );

        const cursorStepOne = {
          transport: 'cursor-transcript',
          request: {
            method: 'CURSOR_TRANSCRIPT',
            path: '/cursor/transcript/abc/turn/1/step/1',
            body: { messages: [{ role: 'user', content: 'inspect files' }] },
          },
          response: {
            status: 200,
            body: {
              content: [
                { type: 'text', text: 'looking' },
                { type: 'tool_use', name: 'Glob', input: { glob_pattern: 'README*' } },
                { type: 'tool_use', name: 'Shell', input: { command: 'ls' } },
              ],
            },
          },
        };
        const cursorStepTwo = {
          transport: 'cursor-transcript',
          request: {
            method: 'CURSOR_TRANSCRIPT',
            path: '/cursor/transcript/abc/turn/1/step/2',
            body: { messages: [{ role: 'user', content: 'inspect files' }] },
          },
          response: {
            status: 200,
            body: {
              content: [
                { type: 'tool_use', name: 'Read', input: { path: 'README.md', limit: 80 } },
              ],
            },
          },
        };
        const otherCursorSession = {
          transport: 'cursor-transcript',
          request: {
            method: 'CURSOR_TRANSCRIPT',
            path: '/cursor/transcript/other/turn/1/step/1',
            body: { messages: [{ role: 'user', content: 'search the web' }] },
          },
          response: {
            status: 200,
            body: {
              content: [
                { type: 'tool_use', name: 'WebSearch', input: { search_term: 'claude-tap' } },
              ],
            },
          },
        };
        context.cursorStepOne = cursorStepOne;
        context.cursorStepTwo = cursorStepTwo;
        context.otherCursorSession = otherCursorSession;
        vm.runInContext('entries = [cursorStepOne, cursorStepTwo, otherCursorSession]', context);
        assert.deepEqual(
          plain(context.getDetailTools(cursorStepOne, cursorStepOne.request.body, cursorStepOne.response.body)
            .map(tool => [context.toolDisplayName(tool), Object.keys(tool.input_schema.properties)])),
          [['Glob', ['glob_pattern']], ['Shell', ['command']], ['Read', ['path', 'limit']]],
        );
        assert.deepEqual(
          plain(context.getDetailTools(otherCursorSession, otherCursorSession.request.body, otherCursorSession.response.body)
            .map(tool => context.toolDisplayName(tool))),
          ['WebSearch'],
        );
        assert.equal(context.cursorTranscriptConversationKey(cursorStepOne), 'abc');
        assert.equal(context.cursorTranscriptConversationKey(otherCursorSession), 'other');
        assert.equal(
          context.cursorTranscriptConversationKey({ capture: { cursor_transcript_id: 'captured-id' } }),
          'captured-id',
        );
        assert.equal(context.getRequestTools(cursorStepOne.request.body).length, 0);
        vm.runInContext('entries = []', context);

        const codexPrefetchId = 'resp_prefetch_tools';
        const codexVisibleId = 'resp_visible';
        const codexExpanded = context.expandWebSocketResponseEntries([
          {
            transport: 'websocket',
            request: {
              method: 'WEBSOCKET',
              path: '/v1/responses',
              body: {
                model: 'gpt-5.6-sol',
                generate: false,
                input: [{
                  type: 'additional_tools',
                  role: 'developer',
                  tools: [
                    { name: 'exec' },
                    { name: 'wait' },
                    { name: 'request_user_input' },
                    { name: 'collaboration' },
                  ],
                }],
              },
            },
            response: {
              body: {
                id: codexPrefetchId,
                generate: false,
                output: [],
                usage: { input_tokens: 10, output_tokens: 0 },
              },
            },
          },
          {
            transport: 'websocket',
            request: {
              method: 'WEBSOCKET',
              path: '/v1/responses',
              body: {
                model: 'gpt-5.6-sol',
                previous_response_id: codexPrefetchId,
                input: [{ type: 'message', role: 'user', content: [{ type: 'input_text', text: 'Run pwd' }] }],
              },
            },
            response: {
              body: {
                id: codexVisibleId,
                previous_response_id: codexPrefetchId,
                output: [{ type: 'message', role: 'assistant', content: [{ type: 'output_text', text: 'ok' }] }],
                usage: { input_tokens: 20, output_tokens: 2 },
              },
            },
          },
        ]);
        assert.equal(codexExpanded.length, 1);
        assert.deepEqual(
          plain(context.getRequestTools(codexExpanded[0].request.body).map(tool => context.toolDisplayName(tool))),
          ['exec', 'wait', 'request_user_input', 'collaboration'],
        );
        assert.deepEqual(
          plain(context.getMessages(codexExpanded[0].request.body).map(message => message.role)),
          ['user'],
        );

        const compactBundle = {
          __claude_tap_compact_trace__: { version: 1 },
          blobs: {
            hash_1: {
              kind: 'json',
              payload: {
                method: 'POST',
                path: '/v1/responses',
                body: { input: [{ role: 'user', content: 'compact prompt' }] },
              },
            },
          },
          records: [{
            __claude_tap_compact_record__: {
              version: 1,
              refs: [{ path: '/request', hash: 'hash_1', bytes: 100 }],
            },
            record: {
              turn: 1,
              request: {
                __claude_tap_blob_ref__: { version: 1, kind: 'json', hash: 'hash_1' },
              },
              response: {
                status: 200,
                body: {
                  output: [{
                    type: 'message',
                    content: [{
                      type: 'output_text',
                      text: 'marker-shaped user payload',
                      metadata: {
                        __claude_tap_blob_ref__: {
                          version: 1,
                          kind: 'json',
                          hash: 'user-controlled-marker-shape',
                        },
                      },
                    }],
                  }],
                },
              },
            },
          }],
        };
        const fakeUserMarker = {
          __claude_tap_blob_ref__: {
            version: 1,
            kind: 'json',
            hash: 'user-controlled-marker-shape',
          },
        };
        assert.deepEqual(plain(context.materializeCompactTraceBundle(compactBundle)), [{
          turn: 1,
          request: {
            method: 'POST',
            path: '/v1/responses',
            body: { input: [{ role: 'user', content: 'compact prompt' }] },
          },
          response: {
            status: 200,
            body: {
              output: [{
                type: 'message',
                content: [{
                  type: 'output_text',
                  text: 'marker-shaped user payload',
                  metadata: fakeUserMarker,
                }],
              }],
            },
          },
        }]);
        assert.deepEqual(
          plain(context.parseTraceText(JSON.stringify(compactBundle))),
          plain(context.materializeCompactTraceBundle(compactBundle)),
        );

        const legacyCompactBundle = {
          __claude_tap_compact_trace__: { version: 1 },
          blobs: {
            hash_legacy_instructions: {
              kind: 'json',
              payload: 'legacy compact instructions',
            },
            hash_legacy_input: {
              kind: 'json',
              payload: {
                role: 'user',
                content: [{ type: 'input_text', text: 'legacy compact input item' }],
              },
            },
          },
          records: [{
            __claude_tap_compact_record__: {
              version: 1,
              encoding: 'json-blob-ref',
            },
            record: {
              turn: 2,
              request: {
                body: {
                  instructions: {
                    __claude_tap_blob_ref__: { version: 1, kind: 'json', hash: 'hash_legacy_instructions' },
                  },
                  input: [
                    {
                      __claude_tap_blob_ref__: { version: 1, kind: 'json', hash: 'hash_legacy_input' },
                    },
                    {
                      role: 'user',
                      content: [{ type: 'input_text', text: 'keep marker shape' }],
                      metadata: fakeUserMarker,
                    },
                  ],
                },
              },
              response: { body: { output: [] } },
            },
          }],
        };
        assert.deepEqual(plain(context.materializeCompactTraceBundle(legacyCompactBundle)), [{
          turn: 2,
          request: {
            body: {
              instructions: 'legacy compact instructions',
              input: [
                {
                  role: 'user',
                  content: [{ type: 'input_text', text: 'legacy compact input item' }],
                },
                {
                  role: 'user',
                  content: [{ type: 'input_text', text: 'keep marker shape' }],
                  metadata: fakeUserMarker,
                },
              ],
            },
          },
          response: { body: { output: [] } },
        }]);

        /* ── normalizeUsage: provider-aware cache flag ── */

        // OpenAI-style: cached_tokens embedded in prompt_tokens via details
        const openaiUsage = context.normalizeUsage({
          prompt_tokens: 100,
          completion_tokens: 50,
          prompt_tokens_details: { cached_tokens: 60 },
        });
        assert.equal(openaiUsage.input_tokens, 100);
        assert.equal(openaiUsage.cache_read_input_tokens, 60);
        assert.equal(openaiUsage._cache_read_in_input, true);

        // Claude/Anthropic-style: cache_read_input_tokens separate from input_tokens
        const claudeUsage = context.normalizeUsage({
          input_tokens: 40,
          output_tokens: 20,
          cache_read_input_tokens: 60,
          cache_creation_input_tokens: 10,
        });
        assert.equal(claudeUsage.input_tokens, 40);
        assert.equal(claudeUsage.cache_read_input_tokens, 60);
        assert.equal(claudeUsage._cache_read_in_input, false);

        // Bedrock Converse-style camelCase: cacheReadInputTokens is a separate bucket
        const bedrockUsage = context.normalizeUsage({
          inputTokens: 9,
          outputTokens: 1,
          cacheReadInputTokens: 12,
          cacheWriteInputTokens: 2,
        });
        assert.equal(bedrockUsage.input_tokens, 9);
        assert.equal(bedrockUsage.cache_read_input_tokens, 12);
        assert.equal(bedrockUsage.cache_creation_input_tokens, 2);
        assert.equal(bedrockUsage._cache_read_in_input, false);

        // No cache data at all: flag should be absent
        const noCacheUsage = context.normalizeUsage({ input_tokens: 100, output_tokens: 50 });
        assert.equal(noCacheUsage.cache_read_input_tokens, undefined);
        assert.equal(noCacheUsage._cache_read_in_input, undefined);

        /* ── Cache hit rate denominator correctness ── */

        // Simulate OpenAI-style: cache embedded in input → rate = 60/100 = 60%
        //   denominator = input_tokens = 100
        const openaiRate = Math.round(60 / 100 * 100);
        assert.equal(openaiRate, 60);

        // Simulate Claude-style: cache separate → total input-side = 40+60+10 = 110
        //   rate = 60/110 = 55% (NOT 60/40 = 150% which is the old buggy result)
        const claudeTotalInput = 40 + 60 + 10;
        const claudeRate = Math.round(60 / claudeTotalInput * 100);
        assert.equal(claudeRate, 55);
        assert.ok(claudeRate <= 100, 'Claude-style rate must not exceed 100%');

        /* ── Direct DOM test: #stat-cache-hit-rate via applyFilter() ── */

        context.assert = assert;
        context.element = element;

        vm.runInContext(`
          // Persistent stat elements so applyFilter can set textContent
          const _statEls = {};
          document.querySelector = function (sel) {
            if (typeof sel === 'string' && sel.startsWith('#')) {
              const id = sel.slice(1);
              if (!_statEls[id]) _statEls[id] = element();
              return _statEls[id];
            }
            return element();
          };
          // Stub heavy rendering helpers irrelevant to stat computation
          renderSidebar = function () {};
          updatePositionIndicator = function () {};
          renderToolFilter = function () {};
          renderPathFilter = function () {};
          renderTracePathBar = function () {};

          function makeUsageEntry(usage, path) {
            return {
              request: { path: path || '/v1/messages', method: 'POST', body: {} },
              response: { body: { usage } },
              turn: '1',
              duration_ms: 100,
            };
          }

          // Claude-style: cache_read separate from input → 60/(40+60+10)=55%
          entries = [makeUsageEntry({
            input_tokens: 40, output_tokens: 20,
            cache_read_input_tokens: 60, cache_creation_input_tokens: 10,
          })];
          activePaths = new Set(['/v1/messages']);
          searchQuery = '';
          activeTools = null;
          applyFilter();
          assert.equal(_statEls['stat-cache-hit-rate'].textContent, '55%',
            'Claude-style direct DOM: expected 55%');
          assert.equal(_statEls['stat-cache-hit-rate-group'].style.display, 'flex',
            'Claude-style direct DOM: group should be visible');

          // OpenAI-style: cache embedded in input → 60/100=60%
          entries = [makeUsageEntry({
            prompt_tokens: 100, completion_tokens: 50,
            prompt_tokens_details: { cached_tokens: 60 },
          })];
          applyFilter();
          assert.equal(_statEls['stat-cache-hit-rate'].textContent, '60%',
            'OpenAI-style direct DOM: expected 60%');

          // Bedrock camelCase: cache_read separate from input → 12/(9+12+2)=52%
          entries = [makeUsageEntry({
            inputTokens: 9, outputTokens: 1,
            cacheReadInputTokens: 12, cacheWriteInputTokens: 2,
          })];
          applyFilter();
          assert.equal(_statEls['stat-cache-hit-rate'].textContent, '52%',
            'Bedrock camelCase direct DOM: expected 52%');

          // No cache data: group should be hidden
          entries = [makeUsageEntry({ input_tokens: 100, output_tokens: 50 })];
          applyFilter();
          assert.equal(_statEls['stat-cache-hit-rate-group'].style.display, 'none',
            'No-cache direct DOM: group should be hidden');

          // Mixed providers: OpenAI(100,cache=60) + Claude(40,cache_read=60,create=10)
          // denom = 100 + 110 = 210, cache_read = 120, rate = 57%
          entries = [
            makeUsageEntry({
              prompt_tokens: 100, completion_tokens: 50,
              prompt_tokens_details: { cached_tokens: 60 },
            }),
            makeUsageEntry({
              input_tokens: 40, output_tokens: 20,
              cache_read_input_tokens: 60, cache_creation_input_tokens: 10,
            }),
          ];
          applyFilter();
          assert.equal(_statEls['stat-cache-hit-rate'].textContent, '57%',
            'Mixed-provider direct DOM: expected 57%');

          // Mixed cached and uncached entries: uncached input still belongs in denominator
          // denom = OpenAI input 100 + uncached input 100, cache_read = 60, rate = 30%
          entries = [
            makeUsageEntry({
              prompt_tokens: 100, completion_tokens: 50,
              prompt_tokens_details: { cached_tokens: 60 },
            }),
            makeUsageEntry({ input_tokens: 100, output_tokens: 10 }),
          ];
          applyFilter();
          assert.equal(_statEls['stat-cache-hit-rate'].textContent, '30%',
            'Mixed cached/uncached direct DOM: expected 30%');
        `, context);
        """
    )

    subprocess.run(["node", "-e", script, str(REPO_ROOT)], check=True, capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for viewer JS unit tests")
def test_viewer_cache_invalidation_diagnostics_units() -> None:
    """The cache diagnosis must only claim a cause the captured payloads support.

    Real Claude Code traffic writes a small delta to the cache on nearly every
    turn, so cache_creation > 0 alone is not evidence of invalidation: only a
    write with no accompanying read means the prefix was genuinely cold.  Once a
    turn does qualify, Anthropic hashes the prompt as an ordered chain — tools,
    then system, then messages — so the earliest changed segment inside the
    cached region is the cause, an edit beyond the last breakpoint is not a
    cause at all, and an idle gap only explains the miss when the declared cache
    lifetime is known and the prompt is unchanged.
    """
    script = textwrap.dedent(
        r"""
        const assert = require('assert/strict');
        const fs = require('fs');
        const path = require('path');
        const vm = require('vm');

        const repoRoot = process.argv.at(-1);
        const assetDir = path.join(repoRoot, 'claude_tap', 'viewer_assets');
        const i18n = JSON.parse(fs.readFileSync(path.join(repoRoot, 'claude_tap', 'viewer_i18n.json'), 'utf8'));

        function classList() {
          return { add() {}, remove() {}, toggle() {}, contains() { return false; } };
        }
        function element() {
          return {
            style: {}, dataset: {}, classList: classList(), children: [],
            innerHTML: '', textContent: '', value: '',
            setAttribute() {}, appendChild(c) { this.children.push(c); return c; },
            addEventListener() {}, querySelector() { return null; },
            querySelectorAll() { return []; }, focus() {}, remove() {},
          };
        }

        const context = {
          console, URLSearchParams,
          setTimeout() {}, clearTimeout() {},
          requestAnimationFrame(cb) { if (typeof cb === 'function') cb(); return 1; },
          cancelAnimationFrame() {},
          __CLAUDE_TAP_I18N__: i18n,
          window: {
            location: { search: '' },
            localStorage: { getItem() { return null; }, setItem() {} },
            matchMedia() { return { matches: false }; },
          },
          navigator: { language: 'en', clipboard: null },
          document: {
            documentElement: { dataset: {}, classList: classList() },
            body: element(),
            querySelector() { return element(); },
            querySelectorAll() { return []; },
            getElementById() { return element(); },
            createElement() { return element(); },
            addEventListener() {}, removeEventListener() {}, execCommand() { return false; },
          },
        };
        vm.createContext(context);

        for (const assetName of [
          'state.js', 'responses.js', 'lazy_loading.js', 'i18n_ui.js',
          'live_bootstrap.js', 'filters_search.js', 'renderers.js', 'diff.js',
          'utilities_mobile.js',
        ]) {
          vm.runInContext(fs.readFileSync(path.join(assetDir, assetName), 'utf8'), context, { filename: assetName });
        }

        const diagnose = context.diagnoseCacheInvalidation;
        const findPredecessor = context.findCachePredecessor;
        // `entries` is a top-level `let`, which lives in the shared script scope
        // rather than on the context object, so it is only reachable from inside
        // the vm.
        const loadEntries = vm.runInContext('(list) => { entries = list; filtered = list.slice(); }', context);
        const setFiltered = vm.runInContext('(list) => { filtered = list; }', context);

        const SYS = 'You are a helpful assistant.';
        const TOOLS = [{ name: 'Read', input_schema: { type: 'object', properties: { path: { type: 'string' } } } }];
        const SESSION = 'sess-unit';

        /* Build a turn shaped like a real Claude Code request: the system prompt
           carries the cache_control breakpoint that tells the viewer which
           segments are cached, and the session header scopes the cache to one
           conversation. */
        function turn(opts) {
          const control = { type: 'ephemeral' };
          if (opts.ttl) control.ttl = opts.ttl;
          const systemText = opts.system === undefined ? SYS : opts.system;
          return {
            request_id: opts.id,
            timestamp: opts.ts,
            request: {
              method: 'POST',
              path: '/v1/messages',
              headers: { 'X-Claude-Code-Session-Id': opts.session === undefined ? SESSION : opts.session },
              body: {
                model: opts.model || 'claude-opus-5',
                // `noBreakpoint` models a capture whose cache_control was stripped.
                system: opts.noBreakpoint ? systemText : [{ type: 'text', text: systemText, cache_control: control }],
                tools: opts.tools === undefined ? TOOLS : opts.tools,
                messages: opts.messages || [{ role: 'user', content: 'hello' }],
              },
            },
            response: { body: { usage: opts.usage } },
          };
        }

        /* A message whose own content block is a breakpoint, so the cached
           prefix reaches into the message list. */
        function cachedMsg(role, text) {
          return { role, content: [{ type: 'text', text, cache_control: { type: 'ephemeral' } }] };
        }

        const COLD = { input_tokens: 20, output_tokens: 30, cache_creation_input_tokens: 35580, cache_read_input_tokens: 0 };
        const WARM = { input_tokens: 9, output_tokens: 55, cache_creation_input_tokens: 718, cache_read_input_tokens: 34905 };
        const SEED = { input_tokens: 12, output_tokens: 40, cache_creation_input_tokens: 35115, cache_read_input_tokens: 0 };

        /* ── Healthy incremental extension: write AND read → no card ── */
        // Measured on a real claude-cli/2.1.233 session: 57 of 64 cache-bearing
        // turns look like this (e.g. create=718 alongside read=34905).
        const seed = turn({ id: 'r1', ts: '2026-08-14T10:00:00Z', usage: SEED });
        const extended = turn({
          id: 'r2', ts: '2026-08-14T10:00:30Z',
          messages: [{ role: 'user', content: 'hello' }, { role: 'assistant', content: 'hi' }],
          usage: WARM,
        });
        assert.equal(diagnose(extended, seed, true), null,
          'a write alongside a read is incremental extension, not invalidation');

        /* ── Nothing earlier left a cache behind → this turn created it ── */
        assert.equal(diagnose(seed, null, false).reasonKey, 'cache_miss_initial');
        assert.equal(diagnose(seed, null, false).lowConfidence, false,
          'the absence of a predecessor is itself conclusive');

        /* ── Prompt-hash order: tools, then system, then messages ── */
        // A schema edit that keeps every tool name still invalidates the cache,
        // so tools are compared by full definition rather than by name.
        const schemaEdited = turn({
          id: 'r3', ts: '2026-08-14T10:00:40Z',
          tools: [{ name: 'Read', input_schema: { type: 'object', properties: { path: { type: 'string' }, limit: { type: 'number' } } } }],
          usage: COLD,
        });
        assert.equal(diagnose(schemaEdited, seed, true).reasonKey, 'cache_miss_tools',
          'a tool schema edit that preserves every name still breaks the cache');

        // A 6.5-minute gap AND a changed system prompt: the actionable cause wins.
        const sysChanged = turn({ id: 'r4', ts: '2026-08-14T10:06:30Z', system: SYS + ' Be terse.', usage: COLD });
        assert.equal(diagnose(sysChanged, seed, true).reasonKey, 'cache_miss_system',
          'a system change must outrank the idle-time explanation');

        // The cached prefix reaches into the messages on both sides, so an edit
        // there is the cause once tools and system match.
        const histPrev = turn({ id: 'r5', ts: '2026-08-14T10:00:00Z', messages: [cachedMsg('user', 'hello')], usage: SEED });
        const histCur = turn({
          id: 'r6', ts: '2026-08-14T10:00:50Z',
          messages: [cachedMsg('user', 'totally different opening')], usage: COLD,
        });
        assert.equal(diagnose(histCur, histPrev, true).reasonKey, 'cache_miss_history');

        // Same edit, but no breakpoint reaches the messages: nothing in the
        // cached region changed, so blaming the history would point the reader at
        // the wrong segment.
        const tailPrev = turn({ id: 'r7', ts: '2026-08-14T10:00:00Z', messages: [{ role: 'user', content: 'hello' }], usage: SEED });
        const tailCur = turn({
          id: 'r8', ts: '2026-08-14T10:00:30Z',
          messages: [{ role: 'user', content: 'totally different opening' }], usage: COLD,
        });
        assert.equal(diagnose(tailCur, tailPrev, true).reasonKey, 'cache_miss_unknown',
          'an edit outside the cached region cannot be reported as an invalidating change');

        /* ── Idle expiry only once the prompt is known to be unchanged ── */
        const idle = turn({ id: 'r9', ts: '2026-08-14T10:07:00Z', usage: COLD });
        const ttlDiag = diagnose(idle, seed, true);
        assert.equal(ttlDiag.reasonKey, 'cache_miss_ttl');
        assert.equal(ttlDiag.lowConfidence, false, 'a confirmed predecessor supports a confident expiry claim');
        assert.ok(ttlDiag.reasonText.includes('5'), 'an ephemeral breakpoint with no ttl is the 5-minute tier');
        assert.ok(!ttlDiag.reasonText.includes('{minutes}'), 'the placeholder must be substituted');

        // An adjacency-only predecessor may not be the turn that owned the
        // cache, so the same verdict is offered with reduced confidence rather
        // than withheld.
        assert.equal(diagnose(idle, seed, false).lowConfidence, true);

        // A 1-hour tier declared on the request must not be judged expired at
        // 7 minutes.
        const longTtlReq = turn({ id: 'r10', ts: '2026-08-14T10:00:00Z', ttl: '1h', usage: SEED });
        assert.equal(diagnose(idle, longTtlReq, true).reasonKey, 'cache_miss_unknown',
          'a 1h request-declared tier is still live after 7 minutes');

        // Anthropic also echoes the billed tier on the response; it wins when present.
        const longTtlResp = turn({
          id: 'r11', ts: '2026-08-14T10:00:00Z',
          usage: { ...SEED, cache_creation: { ephemeral_1h_input_tokens: 35115, ephemeral_5m_input_tokens: 0 } },
        });
        assert.equal(diagnose(idle, longTtlResp, true).reasonKey, 'cache_miss_unknown',
          'the response-side tier outranks the request default');

        // No tier from either source: the lifetime is unknown, so no elapsed
        // gap proves expiry no matter how long it is.
        const untieredPrev = turn({ id: 'r12', ts: '2026-08-14T10:00:00Z', noBreakpoint: true, usage: SEED });
        const halfHourLater = turn({ id: 'r13', ts: '2026-08-14T10:30:00Z', noBreakpoint: true, usage: COLD });
        const untiered = diagnose(halfHourLater, untieredPrev, true);
        assert.equal(untiered.reasonKey, 'cache_miss_unknown',
          'an unknown cache lifetime cannot support an expiry claim at any gap');
        assert.equal(untiered.lowConfidence, true);

        /* ── Engines that embed cache reads in input_tokens report no write counter ── */
        const embedded = turn({
          id: 'r14', ts: '2026-08-14T10:01:00Z',
          usage: { input_tokens: 900, output_tokens: 30, cache_creation_input_tokens: 120, _cache_read_in_input: true },
        });
        assert.equal(diagnose(embedded, seed, true), null,
          'a write counter cannot be interpreted when reads are embedded in input_tokens');

        /* ── Predecessor selection ── */
        // Prompt caches are per-model, so a switch starts cold however similar
        // the prompts look; the earlier model's turn is not a candidate.
        const switched = turn({ id: 'r15', ts: '2026-08-14T10:00:30Z', model: 'claude-sonnet-5', usage: COLD });
        loadEntries([seed, switched]);
        assert.equal(findPredecessor(switched).entry, null, 'a different model never shares a cache');
        assert.equal(diagnose(switched, findPredecessor(switched).entry, false).reasonKey, 'cache_miss_initial');

        // A turn that neither read nor wrote the cache left nothing to reuse.
        const noCache = turn({ id: 'r16', ts: '2026-08-14T10:00:00Z', usage: { input_tokens: 1200, output_tokens: 40 } });
        const afterNoCache = turn({ id: 'r17', ts: '2026-08-14T10:00:30Z', usage: COLD });
        loadEntries([noCache, afterNoCache]);
        assert.equal(findPredecessor(afterNoCache).entry, null, 'a turn without cache activity is not a predecessor');
        assert.equal(diagnose(afterNoCache, findPredecessor(afterNoCache).entry, false).reasonKey, 'cache_miss_initial');

        // Concurrent conversations can share a system prompt, so the nearest
        // earlier turn from another session must not be treated as the owner.
        const otherSession = turn({ id: 'r18', ts: '2026-08-14T10:00:10Z', session: 'sess-other', usage: SEED });
        const mine = turn({ id: 'r19', ts: '2026-08-14T10:00:20Z', usage: COLD });
        loadEntries([seed, otherSession, mine]);
        assert.equal(findPredecessor(mine).entry.request_id, 'r1', 'the predecessor must come from the same session');
        assert.equal(findPredecessor(mine).exact, true, 'a shared session identifier confirms the predecessor');

        // Claude Code rewrites earlier messages as a session grows — reminders
        // move, tool results get compacted — so a genuine predecessor often
        // shares no message prefix at all.  Measured on the 138-turn reference
        // trace, the two expiry turns first differ from their predecessor at
        // message 8 and 37.  The session identifier is what confirms them.
        const rewrittenHead = turn({
          id: 'r20', ts: '2026-08-14T10:07:30Z',
          messages: [{ role: 'user', content: 'hello <system-reminder>moved</system-reminder>' }],
          usage: COLD,
        });
        loadEntries([seed, rewrittenHead]);
        const headPred = findPredecessor(rewrittenHead);
        assert.equal(headPred.entry.request_id, 'r1');
        assert.equal(headPred.exact, true,
          'a shared session confirms a predecessor whose earlier messages were rewritten');

        // Sidebar filters are a viewing choice: hiding a turn must not change
        // the diagnosis of one that is still visible.
        loadEntries([seed, mine]);
        const unfilteredDiag = diagnose(mine, findPredecessor(mine).entry, findPredecessor(mine).exact);
        setFiltered([mine]);
        const filteredPred = findPredecessor(mine);
        assert.equal(filteredPred.entry.request_id, 'r1', 'the predecessor search must walk the unfiltered history');
        assert.deepEqual(diagnose(mine, filteredPred.entry, filteredPred.exact), unfilteredDiag,
          'filtering the sidebar must not change a cache verdict');

        /* ── Every locale defines the diagnostic strings ── */
        const required = ['cache_diag_title', 'cache_miss_system', 'cache_miss_tools',
          'cache_miss_history', 'cache_miss_ttl', 'cache_miss_initial', 'cache_miss_unknown'];
        for (const [loc, table] of Object.entries(i18n)) {
          for (const key of required) {
            assert.ok(table[key], `locale ${loc} is missing ${key}`);
          }
          assert.ok(table['cache_miss_ttl'].includes('{minutes}'),
            `locale ${loc} cache_miss_ttl must carry the {minutes} placeholder`);
        }
        """
    )

    subprocess.run(["node", "-e", script, str(REPO_ROOT)], check=True, capture_output=True, text=True)
