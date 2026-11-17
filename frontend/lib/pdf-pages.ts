export function requirePdfPage(page:number,total:number) {
  if(!Number.isInteger(page)||!Number.isInteger(total)||total<1||page<1||page>total)
    throw new RangeError(`PDF页码必须在1至${total}页之间，未显示替代页`);
  return page;
}
