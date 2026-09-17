// 問題 5 の解答: 鍵ローテーションの手順書を査読します。
// 手順書の間違いは「どこで誰が落ちるか」で言い当てられるので、文章ではなく判定にします。
import {
  SAFE_RUNBOOK,
  STEP_LABELS,
  propagationWaitSeconds,
  retirementWaitSeconds,
} from "./bookstore-rotation-plan.js";
import type { LifespanInput, Step } from "./bookstore-rotation-plan.js";

export type ProblemCode =
  | "missing-step"
  | "switch-before-add"
  | "no-propagation-wait"
  | "no-retirement-wait"
  | "remove-before-switch";

export type RunbookProblem = {
  readonly code: ProblemCode;
  /** 誰がどう落ちるか。運用に渡すのはこの一文です */
  readonly impact: string;
};

const indexOf = (steps: readonly Step[], step: Step): number => steps.indexOf(step);

/** 手順の並びを査読します。判定の順序は固定です */
export function reviewRunbook(steps: readonly Step[]): RunbookProblem[] {
  const problems: RunbookProblem[] = [];
  const flag = (code: ProblemCode, impact: string): void => void problems.push({ code, impact });

  // 足りない手を先に、SAFE_RUNBOOK の順で指摘します
  const present = new Set(steps);
  for (const step of SAFE_RUNBOOK) {
    if (!present.has(step)) flag("missing-step", `${STEP_LABELS[step]} が抜けている`);
  }

  // indexOf は見つからないと -1 を返すので、順序の比較には必ず >= 0 を添えます
  const add = indexOf(steps, "add-key");
  const propagation = indexOf(steps, "wait-propagation");
  const switchSigning = indexOf(steps, "switch-signing");
  const retirement = indexOf(steps, "wait-retirement");
  const remove = indexOf(steps, "remove-old-key");

  if (add >= 0 && switchSigning >= 0 && switchSigning < add) {
    flag("switch-before-add", "JWKS に無い kid のトークンが配られ、すべての検証が落ちる");
  }
  // 待ちは「2 つの手の間にあるか」で判定します（末尾に置いても意味がありません）
  if (add >= 0 && switchSigning > add && !(propagation > add && propagation < switchSigning)) {
    flag("no-propagation-wait", "JWKS を取り直していない検証側だけが、知らない kid で落ちる");
  }
  if (switchSigning >= 0 && remove > switchSigning && !(retirement > switchSigning && retirement < remove)) {
    flag("no-retirement-wait", "古い鍵で署名された、期限内のトークンが検証できなくなる");
  }
  if (remove >= 0 && switchSigning >= 0 && remove < switchSigning) {
    flag("remove-before-switch", "署名に使っている鍵を消すことになり、新しいトークンも検証できない");
  }
  return problems;
}

export function isSafeRunbook(steps: readonly Step[]): boolean {
  return reviewRunbook(steps).length === 0;
}

export type PlannedStep = {
  readonly step: Step;
  /** その手で待つ秒数（待ちの手だけ 0 より大きくなります） */
  readonly waitSeconds: number;
};

/** 待ち時間を埋めた手順書を作ります。数値の出どころは寿命とキャッシュの設定です */
export function planRunbook(input: LifespanInput): PlannedStep[] {
  return SAFE_RUNBOOK.map((step) => {
    if (step === "wait-propagation") return { step, waitSeconds: propagationWaitSeconds(input) };
    if (step === "wait-retirement") return { step, waitSeconds: retirementWaitSeconds(input) };
    return { step, waitSeconds: 0 };
  });
}

/** 手順書を人が読む行にします */
export function runbookLines(input: LifespanInput): string[] {
  return planRunbook(input).map(
    (planned, index) =>
      `${index + 1}. ${STEP_LABELS[planned.step]}` +
      (planned.waitSeconds === 0 ? "" : `（${planned.waitSeconds} 秒待つ）`),
  );
}
