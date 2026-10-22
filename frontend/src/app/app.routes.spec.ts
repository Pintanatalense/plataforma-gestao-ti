import { routes } from './app.routes';

describe('app routes', () => {
  const shell = routes.find((r) => r.path === '' && r.children)!;
  const paths = shell.children!.map((r) => r.path);

  it('exposes the stock categories page (it was implemented but unreachable)', () => {
    expect(paths).toContain('stock/categories');
  });

  it('declares stock/categories before stock/:id so the param route does not swallow it', () => {
    expect(paths.indexOf('stock/categories')).toBeLessThan(paths.indexOf('stock/:id'));
  });
});
