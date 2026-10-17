/** One tool in the sidebar: a summary that expands to its full description and parameters. */

import { useId, useState } from 'react';

import type { Tool } from '../../api/types';
import { firstSentence } from '../../lib/format';
import { describeType } from '../../lib/schema';
import { toolMeta } from '../../lib/toolMeta';
import { Icon } from '../Icon';
import styles from './ToolItem.module.css';

interface ToolItemProps {
  tool: Tool;
  /** Times the agent called this tool in the current conversation. */
  uses: number;
}

export function ToolItem({ tool, uses }: ToolItemProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const properties = Object.entries(tool.parameters.properties ?? {});
  const required = new Set(tool.parameters.required ?? []);
  const meta = toolMeta(tool.name);

  return (
    <li className={styles.item}>
      <button
        type="button"
        className={styles.header}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => {
          setOpen((value) => !value);
        }}
      >
        <span className={styles.chip} data-tone={meta.tone}>
          <Icon name={meta.icon} size={15} />
        </span>
        <span className={styles.titles}>
          <span className={styles.name}>{tool.name}</span>
          <span className={styles.summary}>{firstSentence(tool.description)}</span>
        </span>
        {uses > 0 && (
          <span className={styles.uses} title={`Used ${uses} times in this conversation`}>
            {uses}×
          </span>
        )}
        <Icon name="chevron" size={14} className={open ? styles.chevronOpen : styles.chevron} />
      </button>

      {open && (
        <div id={panelId} className={styles.panel}>
          <p className={styles.description}>{tool.description}</p>
          {properties.length > 0 ? (
            <dl className={styles.params}>
              {properties.map(([name, property]) => (
                <div key={name} className={styles.param}>
                  <dt>
                    <code className={styles.paramName}>{name}</code>
                    <span className={styles.paramType}>{describeType(property)}</span>
                    {required.has(name) ? (
                      <span className={styles.required}>required</span>
                    ) : (
                      property.default !== undefined && (
                        <span className={styles.default}>
                          default {JSON.stringify(property.default)}
                        </span>
                      )
                    )}
                  </dt>
                  {property.description && <dd>{property.description}</dd>}
                </div>
              ))}
            </dl>
          ) : (
            <p className={styles.noParams}>Takes no arguments.</p>
          )}
        </div>
      )}
    </li>
  );
}
