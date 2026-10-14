/**
 * Renders the agent's answers as GitHub-flavoured Markdown (tables, lists,
 * code). Raw HTML in the text is not rendered, so model output can never
 * inject markup or scripts into the page.
 */

import { memo } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

import styles from './Markdown.module.css';

const components: Components = {
  // Links leave the app rather than replacing it, and get no opener access.
  // `node` is react-markdown's AST node; it must not reach the DOM element.
  a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
};

const remarkPlugins = [remarkGfm];

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className={styles.markdown}>
      <ReactMarkdown remarkPlugins={remarkPlugins} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
});
