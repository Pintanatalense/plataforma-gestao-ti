import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { LoginComponent } from './login.component';

describe('Login: nome e logo da empresa', () => {
  const setup = async () => {
    await TestBed.configureTestingModule({
      imports: [LoginComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([]), provideNoopAnimations()]
    }).compileComponents();
    const backend = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(LoginComponent);
    fixture.detectChanges();
    backend.match((r) => r.url.includes('setup')); // status de setup: não interessa aqui
    return { backend, fixture };
  };

  it('shows the company name and logo from the public endpoint', async () => {
    const { backend, fixture } = await setup();
    backend.expectOne('/api/v1/organization/company/public').flush({ name: 'Acme TI', logo_url: '/static/logo.png?v=1' });
    await fixture.whenStable();
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Acme TI');
    expect(el.querySelector('img.company-logo')?.getAttribute('src')).toBe('/static/logo.png?v=1');
  });

  it('keeps the default name when the public endpoint fails', async () => {
    const { backend, fixture } = await setup();
    backend.expectOne('/api/v1/organization/company/public').flush({}, { status: 500, statusText: 'x' });
    await fixture.whenStable();
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Gestão de TI');
    expect(el.querySelector('img.company-logo')).toBeNull();
  });
});
