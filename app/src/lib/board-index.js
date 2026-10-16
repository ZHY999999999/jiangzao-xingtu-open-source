/** 板块查找索引：代码为准，名称和界面显示的裸指数代码也能命中；任何重名都不默默选第一个。 */
export function buildBoardIndex(records) {
  const index = new Map();
  const alias = (key, board) => index.set(key, index.has(key) ? null : board);
  for (const board of records) {
    index.set(board.code, board);
    alias(board.name, board);
    // 界面各处显示的是 881121 而不是 881121.TI；照着显示值敲出来的链接也要能解析。
    const bare = board.code.replace(/\.TI$/i, '');
    if (bare !== board.code) alias(bare, board);
  }
  return index;
}
