interface FrontmatterEntry {
  key: string;
  value: string;
}

interface FrontmatterTableProps {
  entries: FrontmatterEntry[];
}

export function FrontmatterTable({ entries }: FrontmatterTableProps): JSX.Element {
  return (
    <table className="frontmatter-table">
      <tbody>
        {entries.map((entry) => (
          <tr key={entry.key}>
            <td className="frontmatter-key">{entry.key}</td>
            <td className="frontmatter-value">{entry.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
