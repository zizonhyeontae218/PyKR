const assert = require("assert");
const fs = require("fs/promises");
const os = require("os");
const path = require("path");
const vscode = require("vscode");

const pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function waitFor(predicate, timeout = 10000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    const value = await predicate();
    if (value) return value;
    await pause(100);
  }
  throw new Error("통합 테스트 대기 시간 초과");
}

async function open(file) {
  const document = await vscode.workspace.openTextDocument(file);
  await vscode.window.showTextDocument(document);
  return document;
}

async function run() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "pykr-vscode-"));
  const dictionary = path.join(directory, "profile", "GenderChange.Json");
  await vscode.workspace.getConfiguration("pykr").update(
    "dictionaryPath",
    dictionary,
    vscode.ConfigurationTarget.Global,
  );
  await vscode.workspace.getConfiguration("pykr").update(
    "diagnosticsDelay",
    20,
    vscode.ConfigurationTarget.Global,
  );

  const extension = vscode.extensions.getExtension("HT08.pykr");
  assert(extension, "PyKR 확장을 찾을 수 없음");
  await extension.activate();

  try {
    await waitFor(async () => {
      try {
        JSON.parse(await fs.readFile(dictionary, "utf8"));
        return true;
      } catch (_) {
        return false;
      }
    });
    const quoteFile = path.join(directory, "quotes.kpy");
    await fs.writeFile(quoteFile, "", "utf8");
    const quoteDocument = await open(quoteFile);
    assert.strictEqual(quoteDocument.languageId, "kpy");
    await vscode.commands.executeCommand("type", { text: '"' });
    assert.strictEqual(quoteDocument.getText(), '""', "쌍따옴표 자동 닫기 실패");

    const bracketFile = path.join(directory, "brackets.kpy");
    await fs.writeFile(bracketFile, "", "utf8");
    const bracketDocument = await open(bracketFile);
    await vscode.commands.executeCommand("type", { text: "(" });
    assert.strictEqual(bracketDocument.getText(), "()", "괄호 자동 닫기 실패");

    const brokenFile = path.join(directory, "broken.kpy");
    await fs.writeFile(brokenFile, "값 = 1\n퉤(값)\n?퉤(?값)\n", "utf8");
    const brokenDocument = await open(brokenFile);
    const brokenDiagnostics = await waitFor(() => {
      const items = vscode.languages.getDiagnostics(brokenDocument.uri);
      return items.length >= 3 && items;
    });
    assert(brokenDiagnostics.every((item) => item.source === "PyKR"));

    const sourceFile = path.join(directory, "sample.kpy");
    await fs.writeFile(sourceFile, '?값 = 1\n퉤(f"값: {?값}")\n', "utf8");
    const sourceDocument = await open(sourceFile);
    await pause(700);
    assert.deepStrictEqual(vscode.languages.getDiagnostics(sourceDocument.uri), []);
    const semanticTokens = await vscode.commands.executeCommand(
      "vscode.provideDocumentSemanticTokens",
      sourceDocument.uri,
    );
    assert(semanticTokens && semanticTokens.data.length > 0, "시맨틱 색상 토큰 없음");
    await vscode.commands.executeCommand("pykr.toPython");
    const pythonFile = path.join(directory, "sample.py");
    await waitFor(async () => {
      try {
        await fs.access(pythonFile);
        return true;
      } catch (_) {
        return false;
      }
    });
    assert((await fs.readFile(pythonFile, "utf8")).includes("print(f"));

    await vscode.commands.executeCommand("pykr.toKpy");
    const normalizedFile = path.join(directory, "sample.1.kpy");
    await waitFor(async () => {
      try {
        await fs.access(normalizedFile);
        return true;
      } catch (_) {
        return false;
      }
    });
    assert((await fs.readFile(normalizedFile, "utf8")).includes("{?값}"));

    const marker = path.join(directory, "runner-ok.txt");
    const runnerFile = path.join(directory, "runner.kpy");
    await fs.writeFile(
      runnerFile,
      `?파일 = 열기(${JSON.stringify(marker)}, "w", 인코딩="utf-8")\n` +
        '?파일.쓰기("RUNNER_OK")\n?파일.닫기()\n',
      "utf8",
    );
    await open(runnerFile);
    await vscode.commands.executeCommand("pykr.run");
    await waitFor(async () => {
      try {
        return (await fs.readFile(marker, "utf8")) === "RUNNER_OK";
      } catch (_) {
        return false;
      }
    });

    await vscode.commands.executeCommand("pykr.openDictionary");
    assert.strictEqual(
      path.resolve(vscode.window.activeTextEditor.document.uri.fsPath).toLowerCase(),
      path.resolve(dictionary).toLowerCase(),
    );
    await vscode.commands.executeCommand("pykr.validateDictionary");

    const profile = JSON.parse(await fs.readFile(dictionary, "utf8"));
    const printEntry = profile.translation.builtinFunctions.print;
    if (!printEntry.aliases.includes(printEntry.primary)) printEntry.aliases.push(printEntry.primary);
    printEntry.primary = "보여줘";
    await fs.writeFile(dictionary, `${JSON.stringify(profile, null, 2)}\n`, "utf8");
    await vscode.commands.executeCommand("pykr.reloadDictionary");
    const customPythonFile = path.join(directory, "custom.py");
    await fs.writeFile(customPythonFile, 'print("CUSTOM")\n', "utf8");
    await open(customPythonFile);
    await vscode.commands.executeCommand("pykr.toKpy");
    const customKpyFile = path.join(directory, "custom.kpy");
    await waitFor(async () => {
      try {
        return (await fs.readFile(customKpyFile, "utf8")).includes("보여줘");
      } catch (_) {
        return false;
      }
    });

    await fs.writeFile(dictionary, "{ invalid json", "utf8");
    await vscode.commands.executeCommand("pykr.reloadDictionary");
    await waitFor(() => vscode.languages.getDiagnostics(vscode.Uri.file(dictionary)).length > 0);
    const cachedKpyFile = path.join(directory, "cached.kpy");
    await fs.writeFile(cachedKpyFile, '보여줘("CACHED")\n', "utf8");
    await open(cachedKpyFile);
    await vscode.commands.executeCommand("pykr.toPython");
    const cachedPythonFile = path.join(directory, "cached.py");
    await waitFor(async () => {
      try {
        return (await fs.readFile(cachedPythonFile, "utf8")).includes('print("CACHED")');
      } catch (_) {
        return false;
      }
    });
    console.log("PyKR VS Code integration: ok");
  } finally {
    await vscode.commands.executeCommand("workbench.action.closeAllEditors");
    for (const terminal of vscode.window.terminals) {
      if (terminal.name.startsWith("PyKR: ")) terminal.dispose();
    }
    await pause(300);
    await fs.rm(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
}

module.exports = { run };
