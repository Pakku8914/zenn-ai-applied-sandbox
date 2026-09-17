import { useState } from 'react'

// 環境が正しく動くことを確認するための最小コンポーネント。
// ボタンを押すと数が増え、ファイルを保存すると HMR（保存即反映）が効くことを体験できます。
export default function App() {
  const [count, setCount] = useState<number>(0)

  return (
    <main style={{ fontFamily: 'sans-serif', padding: '2rem', lineHeight: 1.8 }}>
      <h1>React + TypeScript サンドボックス</h1>
      <p>環境構築が完了しました。下のボタンを押してみましょう。</p>
      <button type="button" onClick={() => setCount((prev) => prev + 1)}>
        クリック回数: {count}
      </button>
      <p>
        この <code>src/App.tsx</code> を編集して保存すると、画面が自動で更新されます（HMR）。
      </p>
    </main>
  )
}
