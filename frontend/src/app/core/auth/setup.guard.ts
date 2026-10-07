import { CanActivateFn, Router } from '@angular/router';
import { inject } from '@angular/core';
import { AuthService } from './auth.service';
import { map, catchError, of } from 'rxjs';

export const setupGuard: CanActivateFn = (route, state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  return authService.getSetupStatus().pipe(
    map(res => {
      if (res.setup_required) {
        return true;
      }
      return router.createUrlTree(['/login']);
    }),
    catchError(() => of(router.createUrlTree(['/login'])))
  );
};
