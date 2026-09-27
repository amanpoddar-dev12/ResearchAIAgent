export function Citation({ n }: { n: number }) { return <a href={`#source-${n}`} className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">[{n}]</a>; }
