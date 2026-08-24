const path = require("path");
const { runTests } = require("@vscode/test-electron");

async function main() {
  const options = {
    extensionDevelopmentPath: path.resolve(__dirname, ".."),
    extensionTestsPath: path.resolve(__dirname, "integration-test.js"),
    launchArgs: ["--disable-extensions"],
  };
  if (process.env.VSCODE_EXECUTABLE_PATH) {
    options.vscodeExecutablePath = process.env.VSCODE_EXECUTABLE_PATH;
  }
  await runTests(options);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
