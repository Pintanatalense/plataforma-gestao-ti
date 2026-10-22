import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { AuthService } from '../../../core/auth/auth.service';
import { LoginComponent } from './login.component';

describe('LoginComponent', () => {
  let component: LoginComponent;
  let fixture: ComponentFixture<LoginComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LoginComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideAnimationsAsync()
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(LoginComponent);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('after submitting', () => {
    let auth: AuthService;
    let router: Router;

    beforeEach(() => {
      auth = TestBed.inject(AuthService);
      router = TestBed.inject(Router);
      vi.spyOn(auth, 'getSetupStatus').mockReturnValue(of({ setup_required: false }));
      vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
      sessionStorage.clear();
      component.loginForm.setValue({ email: 'a@b.com', password: 'x' });
    });

    it('goes back to the page where the session ended', () => {
      vi.spyOn(auth, 'login').mockReturnValue(of({ access_token: 't', token_type: 'bearer' }));
      auth.rememberReturnUrl('/assets/42');
      component.onSubmit();
      expect(router.navigateByUrl).toHaveBeenCalledWith('/assets/42');
    });

    it('goes to the dashboard when there is nothing to return to', () => {
      vi.spyOn(auth, 'login').mockReturnValue(of({ access_token: 't', token_type: 'bearer' }));
      component.onSubmit();
      expect(router.navigateByUrl).toHaveBeenCalledWith('/');
    });

    it('stops loading when the login fails', () => {
      vi.spyOn(auth, 'login').mockReturnValue(throwError(() => ({ status: 429, error: { error: { message: 'Muitas tentativas inválidas.' } } })));
      component.onSubmit();
      expect(component.isLoading).toBe(false);
      expect(router.navigateByUrl).not.toHaveBeenCalled();
    });
  });

  it('shows the real reason when the account is locked (429), not a generic text', () => {
    const auth = TestBed.inject(AuthService);
    // o componente importa MatSnackBarModule: usa a instância dele, não a da raiz
    const snack = (component as unknown as { snackBar: MatSnackBar }).snackBar;
    const open = vi.spyOn(snack, 'open').mockReturnValue(undefined as never);
    vi.spyOn(auth, 'getSetupStatus').mockReturnValue(of({ setup_required: false }));
    vi.spyOn(auth, 'login').mockReturnValue(
      throwError(() => ({ status: 429, error: { error: { message: 'Muitas tentativas inválidas. Tente novamente em alguns minutos.' } } }))
    );
    component.loginForm.setValue({ email: 'a@b.com', password: 'x' });
    component.onSubmit();
    expect(open.mock.calls[0][0]).toBe('Muitas tentativas inválidas. Tente novamente em alguns minutos.');
  });
});
