/** The public atlas has exactly two THS catalogs. Never guess a cross-provider mapping. */
export function readBoardRoute(hash, findBoard) {
  const params = new URLSearchParams(hash.replace(/^#/, ''));
  const target = params.get('c') || params.get('n') || '';
  const requested = params.get('kind');
  const oldSystem = params.get('sys') === 'sw2021' || /\.SI$/i.test(target);
  const oldLevel = ['sector', 'subindustry'].includes(requested) || ['sector', 'subindustry'].includes(params.get('nk')) || /^884\d{3}\.TI$/i.test(target);
  if (oldSystem || oldLevel) return {
    kind: 'industry', board: '', stock: '', drill: false,
    notice: '原行业树和细分行业入口已收起。现在使用同花顺行业板块，请按名称或板块代码重新选择。',
  };
  const kind = ['industry', 'concept'].includes(requested) ? requested
    : target ? findBoard(target, 'industry') ? 'industry' : 'concept' : 'industry';
  const board = target ? findBoard(target, kind) : null;
  return {
    kind, board: board?.code || '', stock: params.get('s') || '', drill: Boolean(board && params.get('c')),
    notice: target && !board ? '这个链接对应的板块不在当前目录中，请搜索同花顺板块名称或代码。'
      : ['classification', 'supply-chain'].includes(params.get('r')) ? (kind === 'industry' ? '已切换至行业星图，点击连线查看业务联系或共同产业主题的依据。' : '已切换至概念星图，连线表示共同成分股。') : '',
  };
}
