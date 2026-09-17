  from mcp.server.fastmcp import FastMCP

  import data

  mcp = FastMCP("team-dashboard")


  @mcp.tool()
  def summarizeHours(from_: str, to: str, memberId: str = "") -> dict:
      """稼働時間を集計します。

      Args:
          from_: 開始日
          to: 終了日
          memberId: メンバー ID
      """
      summary = data.summarize_hours(from_, to, memberId or None)
      return {"total": summary.total_hours}


  if __name__ == "__main__":
      mcp.run()
