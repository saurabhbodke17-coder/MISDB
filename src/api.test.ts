import { describe, expect, it } from 'vitest';
import { abbreviateWords, display, humanize, queryString } from './api';

describe('API display boundary',()=>{
  it('preserves zero instead of treating it as missing',()=>{expect(display(0)).toBe('0');expect(display(null)).toBe('—');});
  it('encodes user filters without losing special characters',()=>{const q=queryString({search:'a&b = c',batch_id:'',page:2});expect(new URLSearchParams(q).get('search')).toBe('a&b = c');expect(q).not.toContain('batch_id');});
  it('labels source field names readably',()=>{expect(humanize('average_score')).toBe('Average score');});
  it('abbreviates multi-word subject labels without changing source data',()=>{expect(abbreviateWords('Deep Learning')).toBe('DL');expect(abbreviateWords('Data Structures and Algorithms')).toBe('DSA');expect(abbreviateWords('Fundamentals of Data Science')).toBe('FDS');expect(abbreviateWords('Mathematics')).toBe('Mathematics');});
});
