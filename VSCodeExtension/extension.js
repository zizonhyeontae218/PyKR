const vscode = require("vscode");
const cp = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const fsp = require("fs/promises");
const os = require("os");
const path = require("path");

const tokenTypes = [
  "keyword",
  "variable",
  "function",
  "method",
  "type",
  "class",
  "parameter",
  "enumMember",
];

function expandPath(value, document) {
  if (!value) return "";
  if (value === "~" || value.startsWith("~/") || value.startsWith("~\\")) {
    return path.join(os.homedir(), value.slice(2));
  }
  if (path.isAbsolute(value)) return value;
  const folder = document && vscode.workspace.getWorkspaceFolder(document.uri);
  return path.resolve(folder ? folder.uri.fsPath : process.cwd(), value);
}

function samePath(left, right) {
  const normalize = (value) => {
    const resolved = path.resolve(value);
    return process.platform === "win32" ? resolved.toLowerCase() : resolved;
  };
  return normalize(left) === normalize(right);
}

function defaultDictionaryPath() {
  return path.join(os.homedir(), "Documents", "PYKR", "GenderChange.Json");
}

async function copyIfMissing(source, target) {
  try {
    await fsp.copyFile(source, target, fs.constants.COPYFILE_EXCL);
  } catch (error) {
    if (error.code !== "EEXIST") throw error;
  }
}

function dictionaryPath(document) {
  const configured = vscode.workspace
    .getConfiguration("pykr", document ? document.uri : null)
    .get("dictionaryPath", "");
  return expandPath(configured, document) || defaultDictionaryPath();
}

function cachedDictionaryPath(context, profilePath) {
  const key = crypto.createHash("sha256").update(path.resolve(profilePath)).digest("hex");
  return path.join(context.globalStorageUri.fsPath, `${key}.json`);
}

async function pythonPath(document) {
  const configured = vscode.workspace
    .getConfiguration("pykr", document ? document.uri : null)
    .get("pythonPath", "");
  if (configured) return expandPath(configured, document);

  try {
    const extension = vscode.extensions.getExtension("ms-python.python");
    const api = extension && (extension.isActive ? extension.exports : await extension.activate());
    const environment = api && api.environments && api.environments.getActiveEnvironmentPath(document && document.uri);
    if (environment && environment.path) return environment.path;
    const details = api && api.settings && api.settings.getExecutionDetails(document && document.uri);
    if (details && details.execCommand && details.execCommand[0]) return details.execCommand[0];
  } catch (_) {
    // Python 확장이 없거나 API가 달라도 PATH의 Python으로 동작한다.
  }
  return process.platform === "win32" ? "python" : "python3";
}

async function ensureUserFiles(context, document) {
  const targetDictionary = dictionaryPath(document);
  await fsp.mkdir(path.dirname(targetDictionary), { recursive: true });
  await copyIfMissing(context.asAbsolutePath("GenderChange.Json"), targetDictionary);

  const extensionDirectory = path.join(os.homedir(), "Documents", "PYKR", "ExtensionPacks");
  const officialPack = path.join(extensionDirectory, "OfficialExtensionPack.Json");
  await fsp.mkdir(extensionDirectory, { recursive: true });
  await copyIfMissing(
    context.asAbsolutePath(path.join("ExtensionPacks", "OfficialExtensionPack.Json")),
    officialPack,
  );
  return targetDictionary;
}

function bridgeCall(context, request, document) {
  return pythonPath(document).then(
    (python) =>
      new Promise((resolve, reject) => {
        const bridge = context.asAbsolutePath(path.join("VSCodeExtension", "bridge.py"));
        const child = cp.spawn(python, ["-X", "utf8", bridge, "rpc"], {
          cwd: document && document.uri.scheme === "file" ? path.dirname(document.uri.fsPath) : context.extensionPath,
          env: { ...process.env, PYTHONIOENCODING: "utf-8" },
          windowsHide: true,
        });
        let stdout = "";
        let stderr = "";
        child.stdout.setEncoding("utf8");
        child.stderr.setEncoding("utf8");
        child.stdout.on("data", (chunk) => (stdout += chunk));
        child.stderr.on("data", (chunk) => (stderr += chunk));
        child.on("error", reject);
        child.on("close", () => {
          try {
            const response = JSON.parse(stdout);
            if (!response.ok) {
              const error = new Error(response.error || "PyKR 브리지 오류");
              error.line = response.line || 0;
              error.column = response.column || 0;
              reject(error);
            } else {
              resolve(response);
            }
          } catch (error) {
            reject(new Error(stderr || stdout || error.message));
          }
        });
        child.stdin.end(JSON.stringify(request));
      }),
  );
}

function diagnosticFromResult(document, item) {
  const line = Math.min(Math.max(item.line || 0, 0), Math.max(document.lineCount - 1, 0));
  const lineLength = document.lineAt(line).text.length;
  const start = Math.min(Math.max(item.start || 0, 0), lineLength);
  const end = Math.min(Math.max(item.end || start + 1, start + 1), lineLength || 1);
  const diagnostic = new vscode.Diagnostic(
    new vscode.Range(line, start, line, end),
    item.message,
    item.severity === "warning" ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Error,
  );
  diagnostic.source = "PyKR";
  return diagnostic;
}

function activeDocument(language) {
  const editor = vscode.window.activeTextEditor;
  if (!editor || (language && editor.document.languageId !== language)) {
    vscode.window.showErrorMessage(language === "kpy" ? "현재 KPY 파일을 열어줘." : "현재 Python 파일을 열어줘.");
    return undefined;
  }
  return editor.document;
}

async function uniqueTarget(uri, extension) {
  const parsed = path.parse(uri.fsPath);
  for (let index = 0; ; index += 1) {
    const suffix = index ? `.${index}` : "";
    const candidate = vscode.Uri.file(path.join(parsed.dir, `${parsed.name}${suffix}${extension}`));
    try {
      await vscode.workspace.fs.stat(candidate);
    } catch (_) {
      return candidate;
    }
  }
}

function activate(context) {
  const bridge = context.asAbsolutePath(path.join("VSCodeExtension", "bridge.py"));
  const diagnostics = vscode.languages.createDiagnosticCollection("pykr");
  const dictionaryDiagnostics = vscode.languages.createDiagnosticCollection("pykr-dictionary");
  const semanticEmitter = new vscode.EventEmitter();
  const legend = new vscode.SemanticTokensLegend(tokenTypes, []);
  const cache = new Map();
  const pending = new Map();
  const timers = new Map();
  let dictionaryWatcher;
  let dictionaryReloadTimer;

  async function usableDictionaryPath(document) {
    const profilePath = await ensureUserFiles(context, document);
    const cachedPath = cachedDictionaryPath(context, profilePath);
    try {
      await fsp.access(cachedPath);
      return cachedPath;
    } catch (_) {
      return (await validateDictionary(false, profilePath)) ? cachedPath : profilePath;
    }
  }

  async function getAnalysis(document) {
    const key = document.uri.toString();
    const version = document.version;
    const cached = cache.get(key);
    if (cached && cached.version === version) return cached.result;
    const running = pending.get(key);
    if (running && running.version === version) return running.promise;

    const promise = usableDictionaryPath(document)
      .then((profilePath) =>
        bridgeCall(
          context,
          {
            action: "analyze",
            source: document.getText(),
            dictionaryPath: profilePath,
          },
          document,
        ),
      )
      .catch((error) => ({
        diagnostics: [
          {
            line: error.line || 0,
            start: error.column || 0,
            end: (error.column || 0) + 1,
            severity: "error",
            message: error.message,
          },
        ],
        tokens: [],
      }))
      .then((result) => {
        if (document.version === version) cache.set(key, { version, result });
        return result;
      })
      .finally(() => {
        if (pending.get(key)?.promise === promise) pending.delete(key);
      });
    pending.set(key, { version, promise });
    return promise;
  }

  async function publishAnalysis(document) {
    if (document.languageId !== "kpy") return;
    const version = document.version;
    const result = await getAnalysis(document);
    if (document.isClosed || document.version !== version) return;
    diagnostics.set(document.uri, result.diagnostics.map((item) => diagnosticFromResult(document, item)));
    semanticEmitter.fire(document.uri);
  }

  function scheduleAnalysis(document) {
    if (document.languageId !== "kpy") return;
    const key = document.uri.toString();
    clearTimeout(timers.get(key));
    const delay = vscode.workspace.getConfiguration("pykr", document.uri).get("diagnosticsDelay", 350);
    timers.set(key, setTimeout(() => publishAnalysis(document), delay));
  }

  async function validateDictionary(showSuccess = false, requestedPath) {
    const profilePath = requestedPath || (await ensureUserFiles(context));
    let document = vscode.workspace.textDocuments.find(
      (item) => item.uri.scheme === "file" && samePath(item.uri.fsPath, profilePath),
    );
    try {
      const response = await bridgeCall(
        context,
        { action: "validate-dictionary", dictionaryPath: profilePath },
        document,
      );
      const cachedPath = cachedDictionaryPath(context, profilePath);
      await fsp.mkdir(path.dirname(cachedPath), { recursive: true });
      await fsp.writeFile(cachedPath, await fsp.readFile(profilePath));
      if (document) dictionaryDiagnostics.delete(document.uri);
      if (showSuccess) vscode.window.showInformationMessage(response.message);
      return true;
    } catch (error) {
      if (document) {
        dictionaryDiagnostics.set(document.uri, [
          diagnosticFromResult(document, {
            line: error.line || 0,
            start: error.column || 0,
            end: (error.column || 0) + 1,
            message: error.message,
          }),
        ]);
      }
      if (showSuccess) vscode.window.showErrorMessage(error.message);
      return false;
    }
  }

  async function reloadDictionary(showMessage = false) {
    if (!(await validateDictionary(showMessage))) return;
    cache.clear();
    semanticEmitter.fire();
    await Promise.all(
      vscode.workspace.textDocuments.filter((document) => document.languageId === "kpy").map(publishAnalysis),
    );
  }

  function scheduleDictionaryReload() {
    clearTimeout(dictionaryReloadTimer);
    dictionaryReloadTimer = setTimeout(() => reloadDictionary(), 200);
  }

  async function resetDictionaryWatcher() {
    if (dictionaryWatcher) dictionaryWatcher.dispose();
    const profilePath = await ensureUserFiles(context);
    dictionaryWatcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(path.dirname(profilePath), path.basename(profilePath)),
    );
    dictionaryWatcher.onDidChange(scheduleDictionaryReload);
    dictionaryWatcher.onDidCreate(scheduleDictionaryReload);
    dictionaryWatcher.onDidDelete(scheduleDictionaryReload);
  }

  async function convert(direction) {
    const document = activeDocument(direction === "to-python" ? "kpy" : "python");
    if (!document || document.uri.scheme !== "file") return;
    const profilePath = await usableDictionaryPath(document);
    try {
      const response = await bridgeCall(
        context,
        { action: direction, source: document.getText(), dictionaryPath: profilePath },
        document,
      );
      const target = await uniqueTarget(document.uri, direction === "to-python" ? ".py" : ".kpy");
      await vscode.workspace.fs.writeFile(target, Buffer.from(response.content, "utf8"));
      await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(target));
      vscode.window.showInformationMessage(`PyKR 변환 완료: ${path.basename(target.fsPath)}`);
    } catch (error) {
      vscode.window.showErrorMessage(`PyKR 변환 실패: ${error.message}`);
    }
  }

  context.subscriptions.push(
    diagnostics,
    dictionaryDiagnostics,
    semanticEmitter,
    vscode.languages.registerDocumentSemanticTokensProvider(
      { language: "kpy", scheme: "file" },
      {
        onDidChangeSemanticTokens: semanticEmitter.event,
        async provideDocumentSemanticTokens(document) {
          const result = await getAnalysis(document);
          const builder = new vscode.SemanticTokensBuilder(legend);
          for (const token of result.tokens) {
            builder.push(
              new vscode.Range(token.line, token.start, token.line, token.start + token.length),
              token.type,
              [],
            );
          }
          return builder.build();
        },
      },
      legend,
    ),
    vscode.commands.registerCommand("pykr.run", async () => {
      const document = activeDocument("kpy");
      if (!document || document.uri.scheme !== "file") return;
      await document.save();
      const profilePath = await usableDictionaryPath(document);
      const python = await pythonPath(document);
      const terminal = vscode.window.createTerminal({
        name: `PyKR: ${path.basename(document.uri.fsPath)}`,
        shellPath: python,
        shellArgs: ["-X", "utf8", bridge, "run", document.uri.fsPath, "--dictionary", profilePath],
        cwd: path.dirname(document.uri.fsPath),
      });
      terminal.show();
    }),
    vscode.commands.registerCommand("pykr.toPython", () => convert("to-python")),
    vscode.commands.registerCommand("pykr.toKpy", () => convert("to-kpy")),
    vscode.commands.registerCommand("pykr.openDictionary", async () => {
      const profilePath = await ensureUserFiles(context);
      await vscode.window.showTextDocument(await vscode.workspace.openTextDocument(profilePath));
    }),
    vscode.commands.registerCommand("pykr.reloadDictionary", () => reloadDictionary(true)),
    vscode.commands.registerCommand("pykr.validateDictionary", () => validateDictionary(true)),
    vscode.workspace.onDidOpenTextDocument(publishAnalysis),
    vscode.workspace.onDidChangeTextDocument((event) => scheduleAnalysis(event.document)),
    vscode.workspace.onDidSaveTextDocument((document) => {
      if (samePath(document.uri.fsPath, dictionaryPath(document))) scheduleDictionaryReload();
      else publishAnalysis(document);
    }),
    vscode.workspace.onDidCloseTextDocument((document) => {
      diagnostics.delete(document.uri);
      cache.delete(document.uri.toString());
      clearTimeout(timers.get(document.uri.toString()));
    }),
    vscode.workspace.onDidChangeConfiguration(async (event) => {
      if (event.affectsConfiguration("pykr")) {
        await resetDictionaryWatcher();
        await reloadDictionary();
      }
    }),
    { dispose: () => clearTimeout(dictionaryReloadTimer) },
    { dispose: () => dictionaryWatcher && dictionaryWatcher.dispose() },
  );

  resetDictionaryWatcher()
    .then(() => reloadDictionary())
    .catch((error) => vscode.window.showErrorMessage(`PyKR 초기화 실패: ${error.message}`));
}

function deactivate() {}

module.exports = { activate, deactivate };
