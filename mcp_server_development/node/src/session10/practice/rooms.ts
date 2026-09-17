/**
 * 会議室予約のデータ層（練習問題の共通土台）
 *
 * MCP に依存しません。25 件の予約を決定的に生成します。
 */
export const ROOMS = ["room-a", "room-b", "room-c"] as const;
export type RoomId = (typeof ROOMS)[number];

export const RESERVATION_STATUSES = ["reserved", "cancelled", "done"] as const;
export type ReservationStatus = (typeof RESERVATION_STATUSES)[number];

export type Reservation = {
  id: string;
  roomId: RoomId;
  title: string;
  date: string;
  startHour: number;
  hours: number;
  organizerId: string;
  status: ReservationStatus;
  attendees: string[];
  /** 更新のたびに 1 増える。二段階の確定チェックに使う */
  version: number;
};

export type RoomStore = { reservations: Map<string, Reservation> };

const TITLES = ["定例会議", "設計レビュー", "採用面談", "顧客打ち合わせ", "勉強会"];

export function createRoomStore(): RoomStore {
  const reservations = new Map<string, Reservation>();
  for (let i = 0; i < 25; i++) {
    const id = `rsv-${String(i + 1).padStart(3, "0")}`;
    const status: ReservationStatus =
      i % 5 === 0 ? "cancelled" : i % 7 === 0 ? "done" : "reserved";
    reservations.set(id, {
      id,
      roomId: ROOMS[i % ROOMS.length] as RoomId,
      title: `${TITLES[i % TITLES.length] as string}（${i + 1}）`,
      date: `2026-09-${String((i % 10) + 1).padStart(2, "0")}`,
      startHour: 9 + (i % 8),
      hours: 1,
      organizerId: `u-00${(i % 3) + 1}`,
      status,
      attendees: [`u-00${(i % 3) + 1}`],
      version: 1,
    });
  }
  return { reservations };
}

export type SearchParams = {
  roomId?: RoomId;
  date?: string;
  status?: ReservationStatus[];
  query?: string;
  limit: number;
};

export function searchReservations(store: RoomStore, params: SearchParams): Reservation[] {
  const all = [...store.reservations.values()].sort((a, b) => (a.id < b.id ? -1 : 1));
  const matched = all.filter((row) => {
    if (params.roomId !== undefined && row.roomId !== params.roomId) return false;
    if (params.date !== undefined && row.date !== params.date) return false;
    if (params.status !== undefined && params.status.length > 0) {
      if (!params.status.includes(row.status)) return false;
    }
    if (params.query !== undefined && !row.title.includes(params.query)) return false;
    return true;
  });
  return matched.slice(0, params.limit);
}

export function formatReservationLine(row: Reservation): string {
  return `- ${row.id} ${row.title}（${row.roomId} / ${row.date} ${row.startHour}:00-${row.startHour + row.hours}:00 / ${row.status}）`;
}
