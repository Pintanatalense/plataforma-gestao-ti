import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { OrganizationService, Sector } from '../../../core/services/organization.service';
import { SectorDialogComponent } from './sector-dialog.component';

@Component({
  selector: 'app-sector-list',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatDialogModule,
    MatSnackBarModule
  ],
  templateUrl: './sector-list.component.html',
  styleUrls: ['./sector-list.component.scss']
})
export class SectorList implements OnInit {
  private orgService = inject(OrganizationService);
  private dialog = inject(MatDialog);
  private snackBar = inject(MatSnackBar);

  displayedColumns: string[] = ['unit', 'code', 'name', 'status', 'actions'];
  dataSource: Sector[] = [];

  ngOnInit(): void {
    this.loadData();
  }

  loadData() {
    this.orgService.getSectors().subscribe(data => this.dataSource = data);
  }

  openDialog(sector?: Sector) {
    const dialogRef = this.dialog.open(SectorDialogComponent, {
      width: '400px',
      data: sector || null
    });

    dialogRef.afterClosed().subscribe(result => {
      if (result) {
        if (sector) {
          this.orgService.updateSector(sector.id, result).subscribe(() => this.loadData());
        } else {
          this.orgService.createSector(result).subscribe(() => this.loadData());
        }
      }
    });
  }

  deleteSector(id: string) {
    if (confirm('Tem certeza que deseja inativar/remover este setor?')) {
      this.orgService.deleteSector(id).subscribe(() => this.loadData());
    }
  }
}
