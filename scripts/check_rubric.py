import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rubric.schema import load_rubric

RUBRIC_PATH = PROJECT_ROOT / "rubric" / "rubric.yaml"


def main() -> None:
    criteria = load_rubric(RUBRIC_PATH)
    for c in criteria:
        print(f"[{c.id}] {c.name}")
        print(f"  {c.description.strip()}")
        print()


if __name__ == "__main__":
    main()
