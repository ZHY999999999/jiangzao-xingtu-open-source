/** Index quote codes and website detail IDs are separate identifiers. */
const verifiedConceptPages = {
  '886033.TI': 'https://q.10jqka.com.cn/gn/detail/code/309049/',
  '885756.TI': 'https://q.10jqka.com.cn/gn/detail/code/301085/',
};
export function boardCodeInfo(code = '', kind = 'industry') {
  const indexCode = code.replace(/\.TI$/i, '');
  return {
    indexCode, dataCode: code,
    officialUrl: kind === 'industry' && /^881\d{3}\.TI$/i.test(code)
      ? `https://q.10jqka.com.cn/thshy/detail/code/${indexCode}/`
      : verifiedConceptPages[code] || null,
  };
}
