export function Citation({ n, onClick }: { n: number; onClick?: () => void }) {
  return onClick ? <button type="button" aria-label={`Preview source ${n}`} onClick={onClick} className="font-medium text-indigo-600 underline dark:text-indigo-400">[{n}]</button> : <a href={`#source-${n}`} className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">[{n}]</a>;
}
