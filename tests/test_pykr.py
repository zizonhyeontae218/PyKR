from __future__ import annotations

import ast
import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pykr
from Inverter import pykr_ui as core
from Printer.printer import run_kpy


ROOT = Path(__file__).resolve().parent.parent


class PyKRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = core.load_profile(ROOT / "GenderChange.Json")
        cls.forward, cls.reverse, _ = core.load_extensions(
            [ROOT / "ExtensionPacks"]
        )

    def roundtrip(self, source: str) -> str:
        kpy = core.python_to_kpy(source, self.forward, self.profile)
        restored = core.kpy_to_python(kpy, self.reverse, self.profile)
        self.assertEqual(
            ast.dump(ast.parse(source), include_attributes=False),
            ast.dump(ast.parse(restored), include_attributes=False),
        )
        return kpy

    def test_language_constructs_roundtrip(self) -> None:
        cases = [
            '값 = int(input("값: "))\nprint(값)\n',
            '@decorator\nasync def 작업(항목):\n    await 처리(항목)\n',
            '값들 = [숫자 * 2 for 숫자 in range(5) if 숫자]\n합계 = sum(숫자 for 숫자 in 값들)\n',
            '함수 = lambda 인자: 인자 + 1\n결과 = 함수(2)\n',
            'try:\n    with open("x") as 파일:\n        데이터 = 파일.read()\nexcept OSError as 오류:\n    print(오류)\nfinally:\n    pass\n',
            'def 분류(값):\n    match 값:\n        case {"x": x}:\n            return x\n        case _:\n            return None\n',
            '값 = r"print range"\n바이트 = b"print"\n문서 = """print\nrange"""\n# print range\nprint(값)\n',
            '값 = 3\n폭 = 8\n문자 = f"{값!r:>{폭}} {[숫자 for 숫자 in range(값)]} {{literal}}"\n',
            'import random as 무작위\n값 = 무작위.randint(1, 3)\n',
        ]
        if sys.version_info >= (3, 12):
            cases.append("type 벡터 = list[int]\n")
        for source in cases:
            with self.subTest(source=source.splitlines()[0]):
                self.roundtrip(source)

    def test_alias_normalizes_to_primary(self) -> None:
        restored = core.kpy_to_python('퉤("ok")\n', self.reverse, self.profile)
        self.assertEqual(restored, 'print("ok")\n')
        self.assertTrue(
            core.python_to_kpy(restored, self.forward, self.profile).startswith("출력(")
        )

    def test_required_prefix_and_original_location(self) -> None:
        with self.assertRaisesRegex(core.ConversionError, r"\(1:1\)"):
            core.kpy_to_python("값 = 1\n", self.reverse, self.profile)
        with self.assertRaisesRegex(core.ConversionError, r"\(2:4\)"):
            core.kpy_to_python("?값 = 1\n출력(값)\n", self.reverse, self.profile)
        with self.assertRaisesRegex(core.ConversionError, r"\(1:10\)"):
            core.kpy_to_python("?값 = 1 + * 2\n", self.reverse, self.profile)

    def test_profile_validation(self) -> None:
        unsupported = copy.deepcopy(self.profile)
        unsupported["schemaVersion"] = 999
        with self.assertRaises(core.ProfileError):
            core.validate_profile(unsupported)

        duplicate = copy.deepcopy(self.profile)
        duplicate["translation"]["builtinFunctions"]["print"]["aliases"].append(
            duplicate["translation"]["builtinFunctions"]["print"]["primary"]
        )
        with self.assertRaises(core.ProfileError):
            core.validate_profile(duplicate)

        empty = copy.deepcopy(self.profile)
        empty["translation"]["builtinFunctions"]["print"]["primary"] = ""
        with self.assertRaises(core.ProfileError):
            core.validate_profile(empty)
        core.validate_profile(empty, template=True)

    def test_extension_pack_validation(self) -> None:
        pack = {
            "schemaVersion": 999,
            "pack": {"allowPersonalOverride": False},
            "resolution": {"translateByCanonicalPath": True},
            "modules": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps(pack), encoding="utf-8")
            with self.assertRaises(core.ProfileError):
                core.load_extensions(Path(directory))

            pack = {
                "schemaVersion": 1,
                "pack": {
                    "id": "bad",
                    "name": "bad",
                    "version": "1.0.0",
                    "allowPersonalOverride": False,
                },
                "resolution": {
                    "trackImportAliases": True,
                    "translateByCanonicalPath": True,
                },
                "modules": {
                    "tier": {
                        "module": {
                            "members": {
                                "module.member": {
                                    "primary": "멤버",
                                    "aliases": "별칭",
                                }
                            }
                        }
                    }
                },
            }
            path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(core.ProfileError):
                core.load_extensions(Path(directory))

    def test_extension_personal_override_policy(self) -> None:
        def pack(primary: str, allow: bool) -> dict:
            return {
                "schemaVersion": 1,
                "pack": {
                    "id": primary,
                    "name": primary,
                    "version": "1.0.0",
                    "allowPersonalOverride": allow,
                },
                "resolution": {
                    "trackImportAliases": True,
                    "translateByCanonicalPath": True,
                },
                "modules": {
                    "tier": {
                        "module": {
                            "members": {
                                "module.member": {
                                    "primary": primary,
                                    "aliases": [],
                                }
                            }
                        }
                    }
                },
            }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "base"
            personal = root / "personal"
            base.mkdir()
            personal.mkdir()
            (base / "base.json").write_text(
                json.dumps(pack("기본", True), ensure_ascii=False),
                encoding="utf-8",
            )
            (personal / "personal.json").write_text(
                json.dumps(pack("개인", False), ensure_ascii=False),
                encoding="utf-8",
            )
            forward, _, _ = core.load_extensions([base, personal])
            self.assertEqual(forward["module.member"], "개인")

            (base / "base.json").write_text(
                json.dumps(pack("기본", False), ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(core.ProfileError):
                core.load_extensions([base, personal])

    def test_encoding_and_cli_overwrite_protection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "bom.py"
            source.write_bytes('\ufeffprint("ok")\r\n'.encode("utf-8"))
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(pykr.main(["to-kpy", str(source)]), 0)
                target = root / "bom.kpy"
                self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbf"))
                self.assertIn(b"\r\n", target.read_bytes())
                self.assertEqual(pykr.main(["to-kpy", str(source)]), pykr.EXIT_IO)
                self.assertEqual(
                    pykr.main(["to-kpy", str(source), "--overwrite"]),
                    0,
                )

    def test_run_executes_and_cleans_up(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / f"{Path(directory).name}.kpy"
            source.write_text('출력("RUN_OK")\n', encoding="utf-8")
            result = run_kpy(
                source,
                capture_output=True,
                profile=self.profile,
                extension_reverse=self.reverse,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "RUN_OK")
            self.assertFalse(list(Path(tempfile.gettempdir()).glob(f".{source.stem}-*.py")))

    def test_execution_semantics(self) -> None:
        source = (
            "결과 = []\n"
            "for 숫자 in range(6):\n"
            "    if 숫자 % 2:\n"
            "        결과.append(숫자 * 3)\n"
            "print(결과)\n"
        )
        restored = core.kpy_to_python(
            core.python_to_kpy(source, self.forward, self.profile),
            self.reverse,
            self.profile,
        )
        expected = io.StringIO()
        actual = io.StringIO()
        with redirect_stdout(expected):
            exec(compile(source, "<source>", "exec"), {})
        with redirect_stdout(actual):
            exec(compile(restored, "<restored>", "exec"), {})
        self.assertEqual(actual.getvalue(), expected.getvalue())

    def test_generated_stability_corpus(self) -> None:
        templates = (
            lambda i: f"값{i} = {i}\nprint(값{i})\n",
            lambda i: f"def 함수{i}(인자{i}):\n    결과{i} = int(인자{i})\n    return 결과{i}\n",
            lambda i: f"값{i} = [숫자{i} for 숫자{i} in range(3)]\n",
            lambda i: f"값{i} = {{str(키{i}): 키{i} for 키{i} in range(3)}}\n",
            lambda i: f'값{i} = {i}\n문자{i} = f"{{값{i}!r:>4}}"\n',
            lambda i: f"try:\n    값{i} = int('1')\nexcept ValueError as 오류{i}:\n    print(오류{i})\n",
            lambda i: f"함수{i} = lambda 인자{i}: 인자{i} + 1\n",
            lambda i: f"생성기{i} = (숫자{i} for 숫자{i} in range(3))\n",
            lambda i: f"class 클래스{i}:\n    def 메서드{i}(self, 값{i}):\n        return 값{i}\n",
            lambda i: f"값{i} = {i}\n결과{i} = bool(값{i}) and 값{i} or 0\n",
        )
        passed = 0
        total = 1000
        for index in range(100):
            for template in templates:
                self.roundtrip(template(index))
                passed += 1
        print(f"stability-corpus: {passed}/{total} ({passed / total:.2%})")
        self.assertGreaterEqual(passed / total, 0.99)


if __name__ == "__main__":
    unittest.main()
