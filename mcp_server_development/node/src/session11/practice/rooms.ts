/**
 * 会議室予約のデータ層（練習問題の共通土台）
 *
 * MCP に依存しません。30 件の予約を決定的に生成します。
 * 失敗は message ではなく reason（コード）で返します
 * （本文 7 節の「分類はデータ層が持つべき」を反映した形です）。
 */
export const ROOMS = ["room-a", "room-b", "room-c"] as const;
export type RoomId = (typeof ROOMS)[number];

export const RESERVATION_STATUSES = ["reserved", "cancelled", "done"] as const;
export type ReservationStatus = (typeof RESERVATION_STATUSES)[number];

export type ChangeLogEntry = { at: string; actorId: string; action: string };

export type Reservation = {
  id: string;
  roomId: RoomId;
  title: string;
  date: string;
  startHour: number;
  hours: number;
  organizerId: string;
  organizerName: string;
  status: ReservationStatus;
  attendees: string[];
  /** 議題。長くなりがちな項目（一覧に入れてはいけない代表例） */
  agenda: string;
  changeLog: ChangeLogEntry[];
  /** 更新のたびに 1 増える */
  version: number;
};

export type RoomStore = { reservations: Map<string, Reservation> };

export type ReservationSummary = {
  id: string;
  roomId: RoomId;
  title: string;
  date: string;
  startHour: number;
  hours: number;
  status: ReservationStatus;
  organizerName: string;
};

const TITLES = ["定例会議", "設計レビュー", "採用面談", "顧客打ち合わせ", "勉強会"];
const ORGANIZERS = ["佐藤 花子", "鈴木 一郎", "田中 実"];
const AGENDA_LINES = [
  "前回の宿題の確認と、今週の進捗共有を行います。",
  "設計案 A と B のトレードオフを比較し、採用する案を決めます。",
  "リリース判定の基準を確認し、残課題の担当を割り当てます。",
  "顧客からの追加要望について、対応範囲と見積の方針を決めます。",
];

/** 1,000 文字前後の議題を決定的に組み立てる（冗長な詳細を再現するため） */
function longAgenda(): string {
  const lines: string[] = [];
  for (let index = 0; index < 18; index++) {
    lines.push(`${index + 1}. ${AGENDA_LINES[index % AGENDA_LINES.length] ?? ""}`);
  }
  return lines.join("\n");
}

export function createRoomStore(): RoomStore {
  const reservations = new Map<string, Reservation>();
  for (let index = 0; index < 30; index++) {
    const id = `rsv-${String(index + 1).padStart(3, "0")}`;
    const status: ReservationStatus =
      index % 7 === 0 ? "done" : index % 5 === 0 ? "cancelled" : "reserved";
    // rsv-003 だけを「議題が長く、参加者と変更履歴が積み上がった予約」にする
    const bulky = id === "rsv-003";
    reservations.set(id, {
      id,
      roomId: ROOMS[index % ROOMS.length] as RoomId,
      title: `${TITLES[index % TITLES.length] ?? "定例会議"}（${index + 1}）`,
      date: `2026-09-${String((index % 10) + 1).padStart(2, "0")}`,
      startHour: 9 + (index % 8),
      hours: 1,
      organizerId: `u-00${(index % 3) + 1}`,
      organizerName: ORGANIZERS[index % ORGANIZERS.length] ?? "佐藤 花子",
      status,
      attendees: bulky
        ? Array.from({ length: 20 }, (_, seat) => `u-${String(seat + 1).padStart(3, "0")}`)
        : [`u-00${(index % 3) + 1}`],
      agenda: bulky ? longAgenda() : `${TITLES[index % TITLES.length] ?? "定例会議"}の議題です。`,
      changeLog: bulky
        ? Array.from({ length: 25 }, (_, seq) => ({
            at: `2026-08-${String((seq % 28) + 1).padStart(2, "0")}T09:00:00.000Z`,
            actorId: `u-00${(seq % 3) + 1}`,
            action: seq === 0 ? "created" : "updated",
          }))
        : [{ at: "2026-08-01T09:00:00.000Z", actorId: `u-00${(index % 3) + 1}`, action: "created" }],
      version: bulky ? 25 : 1,
    });
  }
  return { reservations };
}

export function toSummary(reservation: Reservation): ReservationSummary {
  return {
    id: reservation.id,
    roomId: reservation.roomId,
    title: reservation.title,
    date: reservation.date,
    startHour: reservation.startHour,
    hours: reservation.hours,
    status: reservation.status,
    organizerName: reservation.organizerName,
  };
}

/** 一覧の 1 行。議題・参加者・履歴は含めない */
export function summaryLine(item: ReservationSummary): string {
  return `- ${item.id} ${item.title}（${item.roomId} / ${item.date} ${item.startHour}:00 から ${item.hours} 時間 / ${item.status} / 主催 ${item.organizerName}）`;
}

export type SearchParams = {
  roomId?: RoomId;
  date?: string;
  status?: ReservationStatus[];
  query?: string;
  limit: number;
  /** 「この ID より後」から返す。カーソルの中身は呼び出し側で不透明にする */
  afterId?: string;
};

export function searchReservations(
  store: RoomStore,
  params: SearchParams,
): { total: number; items: ReservationSummary[]; hasMore: boolean } {
  const all = [...store.reservations.values()].sort((a, b) => (a.id < b.id ? -1 : 1));
  const matched = all.filter((reservation) => {
    if (params.roomId !== undefined && reservation.roomId !== params.roomId) return false;
    if (params.date !== undefined && reservation.date !== params.date) return false;
    if (params.status !== undefined && params.status.length > 0) {
      if (!params.status.includes(reservation.status)) return false;
    }
    if (params.query !== undefined) {
      const needle = params.query.toLowerCase();
      if (!`${reservation.title}\n${reservation.agenda}`.toLowerCase().includes(needle)) {
        return false;
      }
    }
    return true;
  });
  const rest =
    params.afterId === undefined ? matched : matched.filter((row) => row.id > params.afterId!);
  const page = rest.slice(0, params.limit);
  return { total: matched.length, items: page.map(toSummary), hasMore: rest.length > page.length };
}

/** 失敗の理由をコードで返す（message は呼び出し側が組み立てる） */
export type CancelOutcome =
  | { ok: true; releasedHours: number }
  | { ok: false; reason: "not_found" }
  | { ok: false; reason: "not_cancellable"; status: ReservationStatus };

export function cancelReservation(store: RoomStore, reservationId: string): CancelOutcome {
  const reservation = store.reservations.get(reservationId);
  if (reservation === undefined) return { ok: false, reason: "not_found" };
  if (reservation.status !== "reserved") {
    return { ok: false, reason: "not_cancellable", status: reservation.status };
  }
  reservation.status = "cancelled";
  reservation.version += 1;
  reservation.changeLog.push({
    at: "2026-08-20T09:00:00.000Z",
    actorId: reservation.organizerId,
    action: "cancelled",
  });
  return { ok: true, releasedHours: reservation.hours };
}

/**
 * 設備管理システムの空き時間 API（擬似）。failures 回だけ接続エラーを起こしてから成功します。
 * 例外メッセージに内部ホスト名・内部パス・トークンの断片を入れてあります。
 */
export type AvailabilityApi = {
  check: (roomId: RoomId, date: string) => Promise<{ freeHours: number[] }>;
};

export function createAvailabilityApi(options: { failures?: number } = {}): AvailabilityApi {
  let remainingFailures = options.failures ?? 0;
  return {
    async check(roomId, _date) {
      if (remainingFailures > 0) {
        remainingFailures -= 1;
        throw new Error(
          "connect ETIMEDOUT 10.0.34.7:9443 (GET /facility/v1/availability, token=svc_facility_71cd...)",
        );
      }
      const offset = roomId === "room-a" ? 0 : roomId === "room-b" ? 1 : 2;
      return { freeHours: [9, 11, 13, 15, 17].map((hour) => hour + offset) };
    },
  };
}
