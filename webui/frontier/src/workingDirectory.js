export const WORKING_DIRECTORIES_STORAGE_KEY =
  'frontier.workingDirectories.v1';

const WORKING_DIRECTORY_SUFFIX =
  /\r?\n####\r?\n当前工作目录是 [^\r\n]+\r?\n####$/u;

export function stripWorkingDirectoryContext(message) {
  if (typeof message !== 'string') return message;

  const match = WORKING_DIRECTORY_SUFFIX.exec(message);
  return match ? message.slice(0, match.index) : message;
}

export function loadWorkingDirectories(storage) {
  try {
    const targetStorage = storage === undefined
      ? globalThis.localStorage
      : storage;
    const saved = JSON.parse(
      targetStorage?.getItem(WORKING_DIRECTORIES_STORAGE_KEY) || '{}',
    );

    if (!saved || Array.isArray(saved) || typeof saved !== 'object') {
      return {};
    }

    return Object.fromEntries(
      Object.entries(saved).filter(
        ([sessionId, directory]) =>
          sessionId && typeof directory === 'string' && directory.trim(),
      ),
    );
  } catch {
    return {};
  }
}

export function saveWorkingDirectories(
  directories,
  storage,
) {
  try {
    const targetStorage = storage === undefined
      ? globalThis.localStorage
      : storage;
    targetStorage?.setItem(
      WORKING_DIRECTORIES_STORAGE_KEY,
      JSON.stringify(directories),
    );
    return true;
  } catch {
    return false;
  }
}
