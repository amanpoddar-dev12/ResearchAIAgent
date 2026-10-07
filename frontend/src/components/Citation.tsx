export function Citation({ n, onClick }: { n: number; onClick?: () => void }) {
  return onClick ? <button type="button" aria-label={`Preview source ${n}`} onClick={onClick} className="font-medium text-link underline dark:text-link">[{n}]</button> : <a href={`#source-${n}`} className="font-medium text-link hover:underline dark:text-link">[{n}]</a>;
}
