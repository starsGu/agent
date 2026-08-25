import assert from 'node:assert/strict';
import test from 'node:test';

import {
  WORKING_DIRECTORIES_STORAGE_KEY,
  loadWorkingDirectories,
  saveWorkingDirectories,
  stripWorkingDirectoryContext,
} from './workingDirectory.js';

test('strips only a complete trailing working-directory block', () => {
  const stored = [
    'hello',
    '####',
    '当前工作目录是 C:\\Users\\stars',
    '####',
  ].join('\n');

  assert.equal(stripWorkingDirectoryContext(stored), 'hello');
  assert.equal(
    stripWorkingDirectoryContext('hello\n#### Markdown heading'),
    'hello\n#### Markdown heading',
  );
  assert.equal(
    stripWorkingDirectoryContext('hello\n####\n当前工作目录是 C:\\Users\\stars'),
    'hello\n####\n当前工作目录是 C:\\Users\\stars',
  );
});

test('loads and saves session directories without depending on storage', () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
  const directories = {
    'session-1': 'C:\\workspace\\one',
    'session-2': 'D:\\workspace\\two',
  };

  assert.equal(saveWorkingDirectories(directories, storage), true);
  assert.equal(
    values.has(WORKING_DIRECTORIES_STORAGE_KEY),
    true,
  );
  assert.deepEqual(loadWorkingDirectories(storage), directories);
});

test('falls back safely when storage is malformed or unavailable', () => {
  assert.deepEqual(
    loadWorkingDirectories({ getItem: () => '{not-json' }),
    {},
  );
  assert.deepEqual(
    loadWorkingDirectories({ getItem: () => { throw new Error('blocked'); } }),
    {},
  );
  assert.equal(
    saveWorkingDirectories({}, {
      setItem: () => { throw new Error('blocked'); },
    }),
    false,
  );
});
