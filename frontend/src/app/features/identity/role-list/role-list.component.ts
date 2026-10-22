import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { apiErrorMessage } from '../../../core/http/api-error';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';
import { IdentityService, Role } from '../../../core/services/identity.service';
import { RoleDialogComponent } from './role-dialog.component';

@Component({
  selector: 'app-role-list',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatSnackBarModule,
    LoadStateComponent
  ],
  templateUrl: './role-list.component.html',
  styleUrls: ['./role-list.component.scss']
})
export class RoleList implements OnInit {
  private identityService = inject(IdentityService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  displayedColumns: string[] = ['name', 'description', 'permissions', 'actions'];
  dataSource: Role[] = [];

  /** Primeira carga em andamento / falha (uma recarga que falha mantém a tabela e só avisa). */
  isLoading = true;
  loadError: string | null = null;
  private loaded = false;

  ngOnInit(): void {
    this.loadData();
  }

  loadData() {
    if (!this.loaded) {
      this.isLoading = true;
      this.loadError = null;
    }
    this.identityService.getRoles().subscribe({
      next: (data) => {
        this.dataSource = data;
        this.loaded = true;
        this.isLoading = false;
        this.loadError = null;
        this.cdr.markForCheck();
      },
      error: (err) => {
        const msg = apiErrorMessage(err, 'Erro ao carregar perfis.');
        if (this.loaded) {
          this.snackBar.open(msg, 'Fechar', { duration: 4000 });
        } else {
          this.isLoading = false;
          this.loadError = msg;
        }
        this.cdr.markForCheck();
      }
    });
  }

  openDialog(role?: Role) {
    const dialogRef = this.dialog.open(RoleDialogComponent, {
      width: '500px',
      data: role || null
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        if (role) {
          this.identityService.updateRole(role.id, result).subscribe({
            next: () => this.loadData(),
            error: (err) => this.snackBar.open(apiErrorMessage(err, 'Erro ao salvar'), 'Fechar', { duration: 3000 })
          });
        } else {
          this.identityService.createRole(result).subscribe({
            next: () => this.loadData(),
            error: (err) => this.snackBar.open(apiErrorMessage(err, 'Erro ao salvar'), 'Fechar', { duration: 3000 })
          });
        }
      }
    });
  }

  deleteRole(id: string) {
    if (confirm('Tem certeza que deseja remover este perfil?')) {
      this.identityService.deleteRole(id).subscribe({
        next: () => this.loadData(),
        error: (err) => this.snackBar.open(apiErrorMessage(err, 'Erro ao remover perfil'), 'Fechar', { duration: 4000 })
      });
    }
  }
}
