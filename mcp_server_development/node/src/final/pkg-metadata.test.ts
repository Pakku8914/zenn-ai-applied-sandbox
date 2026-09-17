/**
 * 配布物のメタデータのテスト
 *
 * 版がコードと package.json の 2 か所にあると必ずずれます。ここで止めます。
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { PACKAGE_NAME, SERVER_VERSION } from "./version.js";

type Manifest = {
  name?: string;
  version?: string;
  bin?: Record<string, string>;
  exports?: Record<string, string>;
  files?: string[];
  private?: boolean;
};

const manifest = JSON.parse(
  fs.readFileSync(path.resolve("src/final/pkg/package.json"), "utf8"),
) as Manifest;

describe("配布物のメタデータ", () => {
  it("名前と版がコード側と一致する", () => {
    expect(manifest.name).toBe(PACKAGE_NAME);
    expect(manifest.version).toBe(SERVER_VERSION);
  });

  it("bin と exports がビルド後のパスを指す", () => {
    expect(manifest.bin?.[PACKAGE_NAME]).toBe("dist/final/cli.js");
    expect(manifest.exports?.["."]).toBe("./dist/final/index.js");
  });

  it("files が許可リスト方式になっている", () => {
    expect(manifest.files).toEqual(["dist/", "README.md", "LICENSE"]);
  });

  it("private が立っていない（公開できる状態）", () => {
    expect(manifest.private ?? false).toBe(false);
  });
});
