// 利用者が書いた文章をそのまま画面に出す部品（セッション26）。
// サーバーコンポーネント（'use client' を書いていない）。
//
// この部品の見どころは、危ないことを何もしていないことである。
// JSX の {} に入れた文字列は React が必ず「文字」として出すので、
// <script> と書かれていてもタグにはならず、そのまま文字が並ぶ。
//
// もし dangerouslySetInnerHTML を使うと、この安全は消える。名前に
// dangerously（危険なことに）と入っているのは、使う人に手を止めさせるためである。

type UserNoteProps = {
  authorName: string;
  /** 利用者が自由に書いた文章。信頼できない値として扱う */
  body: string;
};

export function UserNote({ authorName, body }: UserNoteProps) {
  return (
    <article>
      {/* 名前も文章も、React が自動でエスケープして出す */}
      <h3>{authorName} さんのメモ</h3>
      <p>{body}</p>
    </article>
  );
}
